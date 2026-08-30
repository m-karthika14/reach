import os

import vertexai
from vertexai.generative_models import GenerativeModel

PROJECT_ID = os.environ["GOOGLE_CLOUD_PROJECT"]
LOCATION = "asia-south1"

vertexai.init(
    project=PROJECT_ID,
    location=LOCATION,
)

model = GenerativeModel("gemini-3.5-flash")

response = model.generate_content(
    "Say hello from REACH in one sentence."
)

print(response.text)
