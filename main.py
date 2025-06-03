import streamlit as st
import pandas as pd
import requests
import re
from io import StringIO
from fastapi import FastAPI, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import threading
from typing import Dict, Optional

# ========== Utility Functions ==========

def extract_username_from_url(url: str) -> Optional[str]:
    patterns = [
        r'leetcode\.com/u/([^/\s]+)',
        r'leetcode\.com/([^/\s]+)/?$'
    ]
    for pattern in patterns:
        match = re.search(pattern, url.strip().rstrip('/'))
        if match:
            return match.group(1)
    return None

def get_leetcode_stats(username: str) -> Optional[Dict]:
    query = """
    query getUserProfile($username: String!) {
        matchedUser(username: $username) {
            username
            submitStats: submitStatsGlobal {
                acSubmissionNum {
                    difficulty
                    count
                    submissions
                }
            }
            tagProblemCounts {
                advanced {
                    tagName
                    tagSlug
                    problemsSolved
                }
                intermediate {
                    tagName
                    tagSlug
                    problemsSolved
                }
                fundamental {
                    tagName
                    tagSlug
                    problemsSolved
                }
            }
            profile {
                realName
                aboutMe
                userAvatar
                location
                skillTags
                websites
                ranking
            }
        }
    }
    """
    variables = {"username": username}
    headers = {
        'Content-Type': 'application/json',
        'Referer': 'https://leetcode.com/',
        'User-Agent': 'Mozilla/5.0'
    }
    response = requests.post(
        'https://leetcode.com/graphql',
        json={'query': query, 'variables': variables},
        headers=headers
    )
    if response.status_code == 200:
        data = response.json()
        if data.get('data') and data['data'].get('matchedUser'):
            return data['data']['matchedUser']
    return None

def fetch_leetcode_stats(username: str) -> dict:
    user = get_leetcode_stats(username)
    if not user:
        raise ValueError("User not found or profile is private")
    stats = user.get('submitStats', {}).get('acSubmissionNum', [])
    return {
        "Username": user.get('username', ''),
        "Real Name": user.get('profile', {}).get('realName', 'N/A'),
        "Total Solved": next((s['count'] for s in stats if s['difficulty'] == 'All'), 0),
        "Easy": next((s['count'] for s in stats if s['difficulty'] == 'Easy'), 0),
        "Medium": next((s['count'] for s in stats if s['difficulty'] == 'Medium'), 0),
        "Hard": next((s['count'] for s in stats if s['difficulty'] == 'Hard'), 0),
        "Worldwide Rank": user.get('profile', {}).get('ranking', 'N/A'),
    }

def process_leaderboard(df: pd.DataFrame) -> pd.DataFrame:
    leaderboard = []
    for url in df["profile_url"]:
        try:
            username = extract_username_from_url(url)
            stats = fetch_leetcode_stats(username)
            leaderboard.append(stats)
        except Exception as e:
            leaderboard.append({
                "Username": "Error",
                "Real Name": "N/A",
                "Total Solved": 0,
                "Easy": 0,
                "Medium": 0,
                "Hard": 0,
                "Worldwide Rank": str(e),
            })
    leaderboard_df = pd.DataFrame(leaderboard)
    leaderboard_df = leaderboard_df.sort_values(by="Total Solved", ascending=False).reset_index(drop=True)
    leaderboard_df.index += 1
    return leaderboard_df

# ========== FastAPI ==========

app = FastAPI()

@app.post("/api/leaderboard")
async def api_leaderboard(csv_file: UploadFile = File(...)):
    try:
        contents = await csv_file.read()
        csv_data = StringIO(contents.decode("utf-8"))
        df = pd.read_csv(csv_data)
        if "profile_url" not in df.columns:
            raise HTTPException(status_code=400, detail="CSV must contain 'profile_url' column")
        leaderboard_df = process_leaderboard(df)
        return JSONResponse(content=leaderboard_df.to_dict(orient="records"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# ========== Streamlit UI ==========

def run_streamlit():
    st.set_page_config(page_title="LeetCode Bulk Analyzer", layout="wide")

    st.title("📊 LeetCode Bulk Profile Analyzer")

    # Option 1: Bulk leaderboard from CSV
    st.header("🏆 Bulk Leaderboard")
    uploaded_file = st.file_uploader("Upload CSV with 'profile_url' column", type=["csv"])

    if uploaded_file:
        try:
            df = pd.read_csv(uploaded_file)
            if "profile_url" not in df.columns:
                st.error("CSV must contain a 'profile_url' column.")
            else:
                leaderboard_df = process_leaderboard(df)
                st.success("Leaderboard generated!")
                st.dataframe(leaderboard_df)

                csv_bytes = leaderboard_df.to_csv(index_label="Rank").encode('utf-8')
                st.download_button(
                    label="Download Leaderboard as CSV",
                    data=csv_bytes,
                    file_name="leetcode_leaderboard.csv",
                    mime="text/csv",
                )
        except Exception as e:
            st.error(f"Error processing file: {e}")

    # Option 2: Detailed single profile view
    st.header("🔍 View Individual Profile")
    profile_url = st.text_input("Enter LeetCode Profile URL")

    if st.button("Get Stats"):
        if profile_url:
            username = extract_username_from_url(profile_url)
            if username:
                st.write(f"Fetching stats for user: *{username}*")
                with st.spinner("Loading profile data..."):
                    user_data = get_leetcode_stats(username)
                if user_data:
                    display_stats(user_data)
                else:
                    st.error("❌ Could not fetch profile data.")
            else:
                st.error("❌ Invalid LeetCode profile URL.")
        else:
            st.warning("⚠ Please enter a LeetCode profile URL")

# ========== Profile Display (from profileShow.py) ==========

def display_stats(user_data: Dict):
    username = user_data.get('username', 'Unknown')
    profile = user_data.get('profile', {})
    submit_stats = user_data.get('submitStats', {})
    topic_data = user_data.get('tagProblemCounts', {})

    col1, col2 = st.columns([1, 2])
    with col1:
        if profile.get('userAvatar'):
            st.image(profile['userAvatar'], width=150)

    with col2:
        st.subheader(f"{username}'s Profile")
        if profile.get('realName'): st.write(f"*Real Name:* {profile['realName']}")
        if profile.get('location'): st.write(f"*Location:* {profile['location']}")

    if submit_stats:
        stats = submit_stats['acSubmissionNum']
        col1, col2, col3, col4 = st.columns(4)
        total = easy = medium = hard = 0
        for s in stats:
            d = s['difficulty'].lower()
            if d == 'all': total = s['count']
            elif d == 'easy': easy = s['count']
            elif d == 'medium': medium = s['count']
            elif d == 'hard': hard = s['count']
        col1.metric("Total", total)
        col2.metric("Easy", easy)
        col3.metric("Medium", medium)
        col4.metric("Hard", hard)

        st.subheader("Difficulty Progress")
        if total:
            st.progress(easy / total)
            st.progress(medium / total)
            st.progress(hard / total)

    if topic_data:
        st.subheader("Topic Categories")
        for cat in ['fundamental', 'intermediate', 'advanced']:
            topics = topic_data.get(cat, [])
            for t in topics:
                if t['problemsSolved'] > 0:
                    st.write(f"🔹 {t['tagName']} ({cat.title()}) — {t['problemsSolved']} problems")

    if profile.get('aboutMe'):
        st.subheader("About")
        st.write(profile['aboutMe'])

    if profile.get('skillTags'):
        st.subheader("Skills")
        st.write(", ".join(profile['skillTags']))

    if profile.get('websites'):
        st.subheader("Websites")
        for site in profile['websites']:
            st.write(site)

# ========== Run Both FastAPI and Streamlit ==========

def start_api():
    uvicorn.run(app, host="0.0.0.0", port=8000)

if _name_ == "_main_":
    threading.Thread(target=start_api, daemon=True).start()
    run_streamlit()
