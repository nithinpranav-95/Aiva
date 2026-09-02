import speech_recognition as sr
import webbrowser
import google.generativeai as genai
import json
import time

# ============================================
# CONFIGURATION — Replace with your key!
# ============================================
GEMINI_API_KEY = "AQ.Ab8RN6Kg214lF209D_UKVnaYBfAIwmJjorFc5opTb_hH7ZpEpA"

# Setup Gemini
genai.configure(api_key=GEMINI_API_KEY)
model_ai = genai.GenerativeModel("gemini-3.6-flash")

# ============================================
# WEBSITES (fallback if LLM fails)
# ============================================
websites = {
    "youtube"  : "https://youtube.com",
    "github"   : "https://github.com",
    "google"   : "https://google.com",
    "netflix"  : "https://netflix.com",
    "linkedin" : "https://linkedin.com",
    "gmail"    : "https://gmail.com",
    "twitter"  : "https://twitter.com",
    "reddit"   : "https://reddit.com",
    "instagram": "https://instagram.com",
    "whatsapp" : "https://web.whatsapp.com",
}

# ============================================
# LISTEN — Captures voice input
# ============================================
def listen():
    r = sr.Recognizer()
    with sr.Microphone() as source:
        print("\n🎤 Listening...")
        r.adjust_for_ambient_noise(source, duration=1)
        try:
            audio = r.listen(source, timeout=5)
        except sr.WaitTimeoutError:
            print("No speech detected!")
            return None
    try:
        text = r.recognize_google(audio)
        print(f"🗣️  You said: {text}")
        return text.lower()
    except sr.UnknownValueError:
        print("❌ Didn't catch that!")
        return None
    except sr.RequestError:
        print("❌ Check internet connection!")
        return None

# ============================================
# ASK LLM — Sends command to Gemini
# ============================================
def ask_llm(command):
    prompt = f"""
    User voice command: "{command}"
    
    Your job: extract what website to open.
    
    Rules:
    - If user says a website name → return that URL
    - If user wants to search → return Google search URL
    - If user says "open YouTube" → return youtube.com
    - If unclear → return Google search with the command
    
    Return ONLY this JSON format, nothing else:
    {{"url": "https://...", "site": "sitename"}}
    
    Examples:
    "open youtube" → {{"url": "https://youtube.com", "site": "YouTube"}}
    "search python tutorials" → {{"url": "https://google.com/search?q=python+tutorials", "site": "Google"}}
    "go to github" → {{"url": "https://github.com", "site": "GitHub"}}
    """

    try:
        print("🧠 Thinking...")
        response = model_ai.generate_content(prompt)
        text = response.text.strip()

        # Clean response
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

        result = json.loads(text)
        return result

    except json.JSONDecodeError:
        print("❌ LLM returned invalid JSON!")
        return None
    except Exception as e:
        print(f"❌ LLM Error: {e}")
        return None

# ============================================
# FALLBACK — Simple keyword matching
# ============================================
def fallback_open(command):
    for site, url in websites.items():
        if site in command:
            return {"url": url, "site": site}
    if "search" in command:
        query = command.replace("search", "").strip()
        query = query.replace(" ", "+")
        return {
            "url": f"https://google.com/search?q={query}",
            "site": "Google Search"
        }
    return None

# ============================================
# MAIN AGENT — Runs the loop
# ============================================
def run_agent():
    print("="*45)
    print("🤖  Gemini Voice Agent — Ready!")
    print("="*45)
    print("💡 Commands you can try:")
    print("   'Open YouTube'")
    print("   'Go to GitHub'")
    print("   'Search Python tutorials'")
    print("   'Open LinkedIn'")
    print("   Say 'stop' or 'exit' to quit!")
    print("="*45)

    while True:
        # Step 1 — Listen
        command = listen()

        if not command:
            continue

        # Step 2 — Check for stop
        if "stop" in command or "exit" in command:
            print("\n👋 Goodbye Nithin!")
            break

        # Step 3 — Ask Gemini
        result = ask_llm(command)

        # Step 4 — Fallback if LLM fails
        if not result:
            print("⚠️  Using fallback matching...")
            result = fallback_open(command)

        # Step 5 — Open website
        if result:
            url  = result["url"]
            site = result.get("site", "website")
            print(f"✅ Opening {site}...")
            print(f"🌐 URL: {url}")
            webbrowser.open(url)
        else:
            print("❌ Couldn't find website!")

        time.sleep(1)

# ============================================
# RUN!
# ============================================
if __name__ == "__main__":
    run_agent()