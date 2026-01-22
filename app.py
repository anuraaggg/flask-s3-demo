from flask import Flask, request, render_template, redirect, url_for, flash
from flask_wtf.csrf import CSRFProtect
from flask_talisman import Talisman
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
import boto3
from botocore.exceptions import ClientError
from datetime import datetime
import os
from dotenv import load_dotenv
import logging
from werkzeug.utils import secure_filename

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'dev-secret-key')
app.config['MAX_CONTENT_LENGTH'] = int(os.getenv('MAX_FILE_SIZE', 5242880))  # Request size limit

# Setup CSRF protection
csrf = CSRFProtect(app)

# Setup rate limiting
limiter = Limiter(
    app=app,
    key_func=get_remote_address,
    default_limits=["200 per day", "50 per hour"]
)

# Setup security headers with Flask-Talisman
Talisman(
    app,
    force_https=False,  # Set to True in production with HTTPS
    strict_transport_security=True,
    strict_transport_security_max_age=31536000,
    content_security_policy={
        'default-src': "'self'",
        'style-src': "'self' 'unsafe-inline'",
        'script-src': "'self'",
        'img-src': "'self' data:",
    },
    content_security_policy_nonce_in=['script-src'],
    x_frame_options='DENY',
    x_content_type_options='nosniff',
    x_xss_protection='1; mode=block',
    referrer_policy='strict-origin-when-cross-origin'
)

# Setup logging with timestamps
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S'
)
logger = logging.getLogger(__name__)

# Load configuration from environment variables
S3_BUCKET = os.getenv('S3_BUCKET')
DYNAMO_TABLE = os.getenv('DYNAMO_TABLE', 'UploadedFiles')
REGION = os.getenv('AWS_REGION', 'ap-south-1')
MAX_FILE_SIZE = int(os.getenv('MAX_FILE_SIZE', 5242880))  # 5MB default
ALLOWED_EXTENSIONS = set(os.getenv('ALLOWED_EXTENSIONS', 'txt,pdf,png,jpg,jpeg,gif,doc,docx').split(','))

if not S3_BUCKET:
    raise ValueError("S3_BUCKET environment variable is not set")


s3 = boto3.client('s3', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(DYNAMO_TABLE)


def validate_aws_connection():
    """Validate AWS S3 and DynamoDB connectivity at startup."""
    try:
        # Check S3 bucket exists
        s3.head_bucket(Bucket=S3_BUCKET)
        logger.info(f'✓ S3 bucket "{S3_BUCKET}" is accessible')
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f'✗ S3 bucket check failed: {error_code}')
        raise RuntimeError(f'Cannot access S3 bucket: {error_code}')
    
    try:
        # Check DynamoDB table exists
        table.load()
        logger.info(f'✓ DynamoDB table "{DYNAMO_TABLE}" is accessible')
    except ClientError as e:
        error_code = e.response.get('Error', {}).get('Code', 'Unknown')
        logger.error(f'✗ DynamoDB table check failed: {error_code}')
        raise RuntimeError(f'Cannot access DynamoDB table: {error_code}')


# Validate AWS connection on startup
try:
    validate_aws_connection()
    logger.info('AWS connection validation passed')
except RuntimeError as e:
    logger.error(f'Startup validation failed: {e}')
    raise


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def format_bytes(size_bytes):
    """Convert bytes to human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB']:
        if size_bytes < 1024:
            return f'{size_bytes:.1f} {unit}'
        size_bytes /= 1024
    return f'{size_bytes:.1f} TB'


# Register Jinja2 filter
app.jinja_env.filters['format_bytes'] = format_bytes


@app.route('/', methods=['GET', 'POST'])
@limiter.limit("5 per minute")
def index():
    if request.method == 'POST':
        try:
            uploaded_file = request.files.get('file')
            
            # Validate file presence
            if not uploaded_file or uploaded_file.filename == '':
                flash('No file selected', 'error')
                logger.warning('Upload attempt with no file')
                return redirect(url_for('index'))
            
            # Validate file extension
            if not allowed_file(uploaded_file.filename):
                flash(f'File type not allowed. Allowed: {{", ".join(ALLOWED_EXTENSIONS)}}', 'error')
                logger.warning(f'Rejected file with disallowed extension: {uploaded_file.filename}')
                return redirect(url_for('index'))
            
            # Validate file size
            uploaded_file.seek(0, os.SEEK_END)
            file_size = uploaded_file.tell()
            uploaded_file.seek(0)
            
            if file_size > MAX_FILE_SIZE:
                flash(f'File too large. Max size: {MAX_FILE_SIZE / 1024 / 1024:.1f}MB', 'error')
                logger.warning(f'Rejected oversized file: {uploaded_file.filename} ({file_size} bytes)')
                return redirect(url_for('index'))
            
            # Sanitize filename
            filename = secure_filename(uploaded_file.filename)
            
            # Add timestamp to prevent duplicates
            name, ext = os.path.splitext(filename)
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            unique_filename = f'{name}_{timestamp}{ext}'
            
            # Upload to S3
            s3.upload_fileobj(uploaded_file, S3_BUCKET, unique_filename)
            logger.info(f'Successfully uploaded {unique_filename} to S3 bucket {S3_BUCKET}')
            
            # Store metadata in DynamoDB
            try:
                table.put_item(
                    Item={
                        'FileName': unique_filename,
                        'Size': file_size,
                        'UploadTime': datetime.now().isoformat()
                    }
                )
                logger.info(f'Stored metadata for {unique_filename} in DynamoDB')
            except ClientError as e:
                error_code = e.response.get('Error', {}).get('Code', 'Unknown')
                if error_code == 'ResourceNotFoundException':
                    error_msg = f'DynamoDB table "{DYNAMO_TABLE}" not found'
                elif error_code == 'AccessDeniedException':
                    error_msg = 'Permission denied: Cannot write to DynamoDB table'
                else:
                    error_msg = f'DynamoDB error: {error_code}'
                logger.error(f'Failed to store metadata in DynamoDB: {error_msg}')
                flash(f'File uploaded to S3 but failed to store metadata: {error_msg}', 'warning')
                return redirect(url_for('index'))
            except Exception as e:
                logger.error(f'Unexpected error storing metadata: {e}')
                flash('File uploaded to S3 but failed to store metadata', 'warning')
                return redirect(url_for('index'))
            
            flash(f'File uploaded successfully', 'success')
            return redirect(url_for('index', uploaded=1))
            
        except ClientError as e:
            error_code = e.response.get('Error', {}).get('Code', 'Unknown')
            logger.error(f'S3 upload failed: {error_code} - {e}')
            flash(f'Upload failed: {error_code}. Please try again.', 'error')
            return redirect(url_for('index'))
        except Exception as e:
            logger.error(f'Unexpected error during upload: {e}')
            flash('An unexpected error occurred during upload', 'error')
            return redirect(url_for('index'))
    
    try:
        response = table.scan()
        items = response.get('Items', [])
        # Sort by UploadTime descending
        items.sort(key=lambda x: x.get('UploadTime', ''), reverse=True)
        logger.info(f'Retrieved {len(items)} items from DynamoDB')
    except Exception as e:
        logger.error(f'Failed to retrieve items from DynamoDB: {e}')
        items = []
        flash('Failed to load file list', 'error')
    
    # Check for uploaded flag in query string to trigger client-side reload
    uploaded_flag = request.args.get('uploaded')
    max_file_size_mb = MAX_FILE_SIZE / 1024 / 1024
    return render_template(
        'index.html',
        items=items,
        uploaded=bool(uploaded_flag),
        max_file_size_mb=f'{max_file_size_mb:.1f}',
        allowed_extensions=', '.join(sorted(ALLOWED_EXTENSIONS))
    )

if __name__ == '__main__':
    app.run(debug=True, port=5001)


@app.errorhandler(413)
def handle_request_too_large(e):
    """Handle 413 Request Entity Too Large error."""
    flash(f'File too large. Max size: {MAX_FILE_SIZE / 1024 / 1024:.1f}MB', 'error')
    logger.warning(f'Rejected upload: Request entity too large')
    return redirect(url_for('index'))


@app.errorhandler(429)
def handle_rate_limit(e):
    """Handle 429 Too Many Requests error."""
    flash('Too many uploads. Please wait a minute before uploading again.', 'error')
    logger.warning(f'Rate limit exceeded for IP: {get_remote_address()}')
    return redirect(url_for('index')), 429

