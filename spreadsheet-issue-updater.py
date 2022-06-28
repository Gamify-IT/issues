from datetime import datetime
#from google.auth.transport.requests import Request
#from google.oauth2.credentials import Credentials
#from google_auth_oauthlib.flow import InstalledAppFlow
#from googleapiclient.discovery import build
#from googleapiclient.errors import HttpError


import re
import json
import base64
import time
import os
import os.path
import requests
import concurrent.futures

github_api_url = "https://api.github.com";
repo_issues_url = "/repos/Gamify-IT/issues/issues?state=all&per_page=100&page=" # page is left empty and filled during the request

# Attaches auth headers and returns results of a GET request
def github_api_request(uri_path : str, timeout=10, api_token="") -> requests.Response:
    headers = {}
    headers['Accept'] = 'application/vnd.github.v3+json'
    if api_token is not None and api_token != "":
        headers['Authorization'] = 'token ' + api_token
    return requests.get((github_api_url + uri_path), headers=headers, timeout=timeout)

def storypoints_of_issue(issue) -> int:
    label: str
    for label in issue.get('labels'):
        match = re.search(r"^\s*storypoint/(\d+)\s*$", label.get('name'))
        if match is not None:
            return match.group(1)

    return None

def query_github_issues() -> list:

    # Read GitHub PAT if present
    pat_path = os.environ.get('GITHUB_PAT_PATH')
    pat = ""
    if pat_path is not None and pat_path != "":
        with open(pat_path) as keyFile:
            pat = keyFile.read();

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
            issues.append({'number': int(issue.get('number')), 'closed_at': issue.get('closed_at'), 'storypoints': storypoints_of_issue(issue)})

    return issues


print(query_github_issues())


