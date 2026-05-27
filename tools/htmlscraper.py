from bs4 import BeautifulSoup
import requests

from inatdatapipeline.inaturalist_auth import INaturalistAuth

auth = INaturalistAuth()
auth.generate_access_token("hspencer1202")

headers = auth.get_auth_headers()
URL = "https://www.inaturalist.org/projects/rare-threatened-endangered-species-of-oregon/members"

html_text = []

page = 1
# while True:
params = {"page": page}
#     response = requests.get(URL, params=params, headers=headers)
response = requests.get(URL, params=params, headers=headers)
print(f"URL: {response.url}")

soup = BeautifulSoup(response.text, "lxml")
with open("data/output/members.html", "w") as fp:
    fp.write(response.text)

print(f"Text:\n{response.text}\n")
print(f"Title: {soup.title}")