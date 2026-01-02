# Flask S3 + DynamoDB Upload Demo

Simple Flask app that uploads files to an S3 bucket and lists recent uploads from a DynamoDB table.

## Requirements
- Python 3.9+
- AWS credentials with access to the target S3 bucket and DynamoDB table
- Configured bucket/table in `app.py` (or override via your own config)

## Setup (Windows PowerShell)
1. Create a virtual environment:
   ```pwsh
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   ```
2. Install dependencies:
   ```pwsh
   pip install flask boto3
   ```
3. Configure AWS credentials (e.g., `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, and optionally `AWS_DEFAULT_REGION`), or use an AWS profile that already has S3+DynamoDB permissions.
4. Update `S3_BUCKET`, `DYNAMO_TABLE`, and `REGION` in `app.py` to match your AWS resources.

## Run the app
```pwsh
python app.py
```
Then open http://localhost:5001.

## How it works
- POST `/` uploads the selected file to S3 using the configured bucket.
- GET `/` reads the DynamoDB table and lists items, sorted by `UploadTime` descending.
- A one-time banner appears after upload and refreshes the page to show the latest DynamoDB state.

## Expected DynamoDB item shape
The template expects each item to provide at least:
- `FileName`
- `Size` (bytes)
- `UploadTime` (string that sorts correctly in descending order, e.g., ISO 8601)

## Project layout
- `app.py` – Flask entrypoint and AWS clients
- `templates/index.html` – upload form and table view
- `static/styles.css` – basic styling

## Notes
- For production, avoid hard-coding AWS resource names; prefer environment variables or a config file.
- Consider server-side validation (size/type) before uploading to S3.
- Enable proper IAM least-privilege policies for the S3 bucket and DynamoDB table.
