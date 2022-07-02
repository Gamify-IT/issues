from datetime import datetime
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError


import re
import json
import base64
import time
import os
import os.path
import requests
import concurrent.futures

import google.auth

github_api_url = "https://api.github.com/";
repo_issues_url = "repos/Gamify-IT/issues/issues?state=all&per_page=100&page=" # page is left empty and filled during the request

google_oauth_scopes = ['https://www.googleapis.com/auth/spreadsheets']
google_sheets_updateable_range = "Issues!A2:C"

# Reads the content of a file and ensures that leading and trailing whitespace will be stripped
def readFileContent(filename):
    try:
        with open(filename) as file:
            return file.read().strip()
    except Error as error:
        print(f"Cannot open/find {filename}.\nError: {error}\nExiting...")
        exit(-1)

google_sheet_id = readFileContent('sheet-id.txt')

# Attaches auth headers and returns results of a GET request
def github_api_request(uri_path : str, timeout=10, api_token="") -> requests.Response:
    headers = {}
    headers['Accept'] = 'application/vnd.github.v3+json'
    if api_token is not None and api_token != "":
        headers['Authorization'] = 'token ' + api_token
    return requests.get((github_api_url + uri_path), headers=headers, timeout=timeout)

# Calculates for a given GitHub issue how many storypoints it has
def storypoints_of_issue(issue) -> int:
    label: str
    for label in issue.get('labels'):
        match = re.search(r"^\s*storypoint/(\d+)\s*$", label.get('name'))
        if match is not None:
            return match.group(1)

    return None

# Returns all currently known GitHub issues as a list of objects
def query_github_issues() -> list:

    # Read GitHub PAT if present
    pat_path = os.environ.get('GITHUB_PAT_PATH')
    pat = ""
    if pat_path is not None and pat_path != "":
        pat = readFileContent(pat_path)

    page = 1
    issues = []
    while True:
        response = github_api_request(repo_issues_url + str(page), 10, api_token=pat)

        # Response is an empty array -> there are no more issues to query
        if len(response.json()) < 1:
            break

        # Sleep until the rate limit has been reset
        if int(response.headers.get('x-ratelimit-remaining', 2)) <= 1:
            resetTime = datetime.fromtimestamp(response.headers.get('x-ratelimit-reset'))
            print("Sleeping until " + resetTime.strftime("%d.%m%Y, %H:%M:%S"))
            time.sleep((resetTime - datetime.utcnow()).total_seconds())

        currentIssues: list = response.json()
        page += 1
        for issue in currentIssues:
            issues.append({'number': int(issue.get('number')), 'closed_at': datetime.fromisoformat(issue.get('closed_at').replace('Z', '')).strftime('%Y-%m-%d') if issue.get('closed_at') is not None else None, 'storypoints': storypoints_of_issue(issue)})

    return issues

# Creates the OAuth token for the Google Sheets API from the token.json file, or creates a new one using credentials.json
def get_oauth_token():
    credentials = None
    # The file token.json stores the user's access and refresh tokens, and is
    # created automatically when the authorization flow completes for the first
    # time.
    if os.path.exists('token.json'):
        credentials = Credentials.from_authorized_user_file('token.json', google_oauth_scopes)
    # If there are no (valid) credentials available, let the user log in.
    if not credentials or not credentials.valid:
        if credentials and credentials.expired and credentials.refresh_token:
            credentials.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', google_oauth_scopes)
            credentials = flow.run_local_server(port=0)
        # Save the credentials for the next run
        with open('token.json', 'w') as token:
            token.write(credentials.to_json())
    return credentials

# Updates the Spreadsheet with the given issues
def update_google_spreadsheets(issues):

    # Build the body of the request
    request_body = { "range": google_sheets_updateable_range, "majorDimension": "ROWS", "values": [ [issue.get('number'), issue.get('storypoints'), issue.get('closed_at')] for issue in issues] }

    # Execute the update
    try:
        response = build('sheets', 'v4', credentials=get_oauth_token())\
            .spreadsheets()\
            .values()\
            .update(spreadsheetId=google_sheet_id, range=google_sheets_updateable_range, valueInputOption="USER_ENTERED",
                body=request_body)\
            .execute()
        print(response)
    except HttpError as err:
        print(f"An error occurred: {err}")
        exit(-2)

issues = sorted(query_github_issues(), key=lambda issue: issue.get('number'))
print(json.dumps(issues, indent=4))
update_google_spreadsheets(issues)
print("Successfully updated the Google Docs Sheet")


