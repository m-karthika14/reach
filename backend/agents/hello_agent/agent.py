from google.adk.agents import Agent


def root_agent():
    return Agent(
        name="hello_agent",
        model="gemini-2.5-flash",
        description="A simple hello agent for REACH.",
        instruction="You are a helpful assistant. Reply warmly and briefly.",
    )
