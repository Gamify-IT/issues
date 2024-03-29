from typing import Union, TypeVar
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
google_sheets_updateable_range = "Issues!A2:F"

def readFileContent(filename: str, ignore_missing:bool=False) -> str:
    """
    Reads the content of a file and ensures that leading and trailing whitespace will be stripped.
    If ignore_missing and the file is not present, "" will be returned
    """
    try:
        with open(filename) as file:
            return file.read().strip()
    except FileNotFoundError as error:
        if not ignore_missing:
            print(f"Cannot open/find {filename}.\nError: {error}\nExiting...")
            exit(-1)
        else:
            return ""

def convertIsoTimestamp(timestamp: Union[str, datetime]) -> datetime:
    """
    Converts a timestamp in iso format ('2022-06-31T23:59:00Z') to a datetime
    """
    if isinstance(timestamp, datetime): # No-op if we already converted the datetime
        return timestamp
    if timestamp is None:
        return None
    return datetime.fromisoformat(timestamp.replace('Z', ''))

google_sheet_id = readFileContent('sheet-id.txt')

raw_start_date = readFileContent('project-start-iso.txt')
project_start_date = datetime.min if raw_start_date == "" else convertIsoTimestamp(raw_start_date)

T = TypeVar("T")
def get_or_default(dictionary: dict, key: str, default: T) -> T:
    # There are two cases: 1. entry not in the dict, 2. entry in the dict is None
    result = dictionary.get(key, default)
    return default if result is None else result


# Converts the given datetime into a string that is intended for humans, not computers
def to_human_date(instant: datetime) -> str:
    return instant.strftime('%d.%m.%Y, %H:%M:%S')

# Converts a timestamp returned from the GitHub API (format '2022-06-31T23:59:00Z') to a date format useful for Google Docs (YYYY-mm-dd)
def convertGitHubTimestampToGoogleDate(api_timestamp: str) -> str:
    instant = convertIsoTimestamp(api_timestamp)
    return None if instant is None else instant.strftime('%Y-%m-%d')

latest_github_api_response: str = ""

def is_issue_for_this_project(issue: dict) -> bool:
    """
    Filters out issues that do not belong to the current project.
    If this method returns true, the issue belongs to the current project
    """
    if project_start_date is None:
        return True # The current project was started with issue 1, so all issues are valid
    if convertIsoTimestamp(get_or_default(issue,'created_at', datetime.min)) >= project_start_date:
        return True
    if convertIsoTimestamp(get_or_default(issue,'updated_at', datetime.min)) >= project_start_date:
        return True
    if convertIsoTimestamp(get_or_default(issue,'closed_at', datetime.min)) >= project_start_date:
        return True
    return False

# Attaches auth headers and returns results of a GET request
def github_api_request(uri_path : str, timeout=10, api_token="") -> requests.Response:
    headers = {}
    headers['Accept'] = 'application/vnd.github.v3+json'
    if api_token is not None and api_token != "":
        headers['Authorization'] = 'token ' + api_token
    response = requests.get((github_api_url + uri_path), headers=headers, timeout=timeout)
    global latest_github_api_response
    latest_github_api_response = f"{response.headers.get('x-ratelimit-remaining')} requests to the GitHub API remain. Resetting at {to_human_date(datetime.fromtimestamp(int(response.headers.get('x-ratelimit-reset'))))}"
    return response

# Calculates for a given GitHub issue how many storypoints it has
def storypoints_of(issue) -> int:
    label: str
    for label in issue.get('labels'):
        match = re.search(r"^\s*storypoint/(\d+)\s*$", label.get('name'))
        if match is not None:
            return match.group(1)

    return None

matches_dod_completely = 'komplett'
matches_dod_partly = 'teilweise'
matches_dod_not_at_all = 'gar nicht'

# Checks for a given GitHub issue if it fulfills its dod
def fulfills_dod(issue) -> str:
    body = issue.get('body')
    if body is None:
        return matches_dod_completely
    openTasks = len(re.findall(r'^\s*- \[ \]\s*', body, flags=re.MULTILINE))
    closedTasks = len(re.findall(r'^\s*- \[x\]\s*', body, flags=re.MULTILINE))
    #print(body, openTasks, closedTasks)
    if openTasks == 0:
        return matches_dod_completely
    elif closedTasks > 0: # Some are open, some closed
        return matches_dod_partly
    else:
        return matches_dod_not_at_all

# Checks for a given GitHub issue whether it is labeled as a bug
def is_bug(issue) -> bool:
    for label in issue.get('labels'):
        match = re.search(r"^\s*bug\s*$", label.get('name'))
        if match is not None:
            return True
    return False

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

        # Response is an empty array -> there are no more issues to query (There is no other way to get the total number of issues in a repo)
        if len(response.json()) < 1:
            break

        # Sleep until the rate limit has been reset
        if int(response.headers.get('x-ratelimit-remaining', 2)) <= 1:
            resetTime = datetime.fromtimestamp(response.headers.get('x-ratelimit-reset'))
            print("Sleeping until " + to_human_date(resetTime))
            time.sleep((resetTime - datetime.utcnow()).total_seconds())

        currentIssues: list = response.json()
        page += 1
        for issue in currentIssues:
            if is_issue_for_this_project(issue):
                issues.append({
                    'number': int(issue.get('number')),
                    'created_at': convertGitHubTimestampToGoogleDate(issue.get('created_at')),
                    'closed_at': convertGitHubTimestampToGoogleDate(issue.get('closed_at')),
                    'storypoints': storypoints_of(issue),
                    'is_bug': is_bug(issue),
                    'dod_fulfilled': fulfills_dod(issue),
                    })

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
    request_body = {
            "range": google_sheets_updateable_range,
            "majorDimension": "ROWS",
            "values": [
                [   issue.get('number'),
                    issue.get('storypoints'),
                    issue.get('created_at'),
                    issue.get('closed_at'),
                    issue.get('is_bug'),
                    issue.get('dod_fulfilled')
                    ] for issue in issues
                ]
            }

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
print(latest_github_api_response)
print(f"Successfully updated the Google Docs Sheet at {to_human_date(datetime.now())}")


