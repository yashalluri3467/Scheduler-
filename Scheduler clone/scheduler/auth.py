import os
import json
from google.oauth2 import service_account

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_credentials():
    try:
        creds_json = os.environ.get("GOOGLE_CREDENTIALS")

        if not creds_json:
            raise Exception("Missing GOOGLE_CREDENTIALS env variable")

        creds_dict = json.loads(creds_json)

        credentials = service_account.Credentials.from_service_account_info(
            creds_dict,
            scopes=SCOPES
        )

        return credentials

    except Exception as e:
        raise Exception(f"Auth Error: {str(e)}")
