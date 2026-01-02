from flask import Flask, request, render_template, redirect, url_for
import boto3
from datetime import datetime

app = Flask(__name__)


S3_BUCKET = 'aws-project-da2'
DYNAMO_TABLE = 'UploadedFiles'
REGION = 'ap-south-1'  


s3 = boto3.client('s3', region_name=REGION)
dynamodb = boto3.resource('dynamodb', region_name=REGION)
table = dynamodb.Table(DYNAMO_TABLE)


@app.route('/', methods=['GET', 'POST'])
def index():
    if request.method == 'POST':
        uploaded_file = request.files['file']
        if uploaded_file.filename != '':
            s3.upload_fileobj(uploaded_file, S3_BUCKET, uploaded_file.filename)
        return redirect(url_for('index', uploaded=1))
    response = table.scan()
    items = response.get('Items', [])
    # Sort by UploadTime descending
    items.sort(key=lambda x: x.get('UploadTime', ''), reverse=True)
    
    # Check for uploaded flag in query string to trigger client-side reload
    uploaded_flag = request.args.get('uploaded')
    return render_template('index.html', items=items, uploaded=bool(uploaded_flag))

if __name__ == '__main__':
    app.run(debug=True, port=5001)

