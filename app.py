from flask import Flask, request, render_template, redirect, url_for, flash
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

# Setup logging
logging.basicConfig(level=logging.INFO)
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


def allowed_file(filename):
    """Check if file extension is allowed."""
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


@app.route('/', methods=['GET', 'POST'])
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
            
            # Upload to S3
            s3.upload_fileobj(uploaded_file, S3_BUCKET, filename)
            logger.info(f'Successfully uploaded {filename} to S3 bucket {S3_BUCKET}')
            flash(f'File {filename} uploaded successfully', 'success')
            return redirect(url_for('index', uploaded=1))
            
        except ClientError as e:
            error_code = e.response['Error']['Code']
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
    return render_template('index.html', items=items, uploaded=bool(uploaded_flag))

if __name__ == '__main__':
    app.run(debug=True, port=5001)

