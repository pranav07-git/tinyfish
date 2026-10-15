from tinyfish import TinyFish, RunStatus
from dotenv import load_dotenv
import json

load_dotenv()
client = TinyFish()

# GOAL = (
#     "Find software or AI internships for students. "
#     "Return JSON: a list of role, location, deadline, link."
# )

# URL = "https://www.janestreet.com/join-jane-street/open-roles/"
# run = client.agent.run(url=URL, goal=GOAL)

# if run.status == RunStatus.COMPLETED:
#     print(run.result)


import json
from dotenv import load_dotenv
from tinyfish import TinyFish, RunStatus

load_dotenv()

# Initialize TinyFish client
client = TinyFish()

# Companies and their careers pages
PAGES = {
    "Jane Street": "https://www.janestreet.com/join-jane-street/open-roles/",
    "Google": "https://www.google.com/about/careers/applications/",
    "Microsoft": "https://careers.microsoft.com/",
}


GOAL = """
Find software engineering, software development, or AI internships
suitable for students.
"""

rows = []

for company, url in PAGES.items():
    print(f"\nSearching {company}...")

    try:
        run = client.agent.run(
            url=url,
            goal=GOAL
        )

        if run.status == RunStatus.COMPLETED:
            rows.append({
                "company": company,
                "url": url,
                "roles": run.result
            })
            print(f"Completed: {company}")

        else:
            print(f"Failed: {company} — status: {run.status}")

    except Exception as error:
        print(f"Error searching {company}: {error}")


with open("internships.json", "w", encoding="utf-8") as file:
    json.dump(rows, file, indent=2, ensure_ascii=False)

print(f"\nDone! Results saved for {len(rows)} companies.")

