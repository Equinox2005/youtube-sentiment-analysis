from googleapiclient.discovery import build
from youtube_transcript_api import YouTubeTranscriptApi
import pandas as pd
import os
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB

###  YouTube API Key (Replace with your actual key)
API_KEY = "Your API Key"


### Load Sentiment140 and Train Model
def load_sentiment140():
    dataset_path = "sentiment140.csv"
    if not os.path.exists(dataset_path):
        print(f"Error: {dataset_path} not found. Please download Sentiment140 dataset.")
        exit(1)

    df = pd.read_csv(dataset_path, encoding="latin1", usecols=[0, 5], names=["sentiment", "text"])
    df["sentiment"] = df["sentiment"].replace({0: "neg", 4: "pos"})

    return df


def train_sentiment_model():
    df = load_sentiment140()
    vectorizer = CountVectorizer(max_features=2000)
    X = vectorizer.fit_transform(df["text"])
    y = df["sentiment"]
    model = MultinomialNB()
    model.fit(X, y)
    return model, vectorizer


### Predict Sentiment
def predict_sentiment(text, model, vectorizer):
    text_vector = vectorizer.transform([text])
    prediction = model.predict(text_vector)
    return prediction[0]


### Get YouTube Video Transcript
def get_video_transcript(video_id):
    try:
        transcript = YouTubeTranscriptApi.get_transcript(video_id)
        transcript_text = " ".join([t["text"] for t in transcript])
        return transcript_text
    except Exception as e:
        print("Transcript not available:", e)
        return None


###  Fetch YouTube Comments with Pagination & Sorting Options
def get_youtube_comments(video_id, max_comments=500, sort_by="relevance"):
    """
    Fetches up to `max_comments` YouTube comments using pagination.
    :param video_id: YouTube video ID
    :param max_comments: Number of comments to fetch
    :param sort_by: "relevance" (top comments) or "time" (latest comments)
    """
    youtube = build("youtube", "v3", developerKey=API_KEY)
    comments = []
    request = youtube.commentThreads().list(
        part="snippet",
        videoId=video_id,
        maxResults=100,  # Fetches 100 comments per request
        textFormat="plainText",
        order=sort_by  #  Fetches top comments instead of latest
    )

    while request and len(comments) < max_comments:
        response = request.execute()
        for item in response.get("items", []):
            comment = item["snippet"]["topLevelComment"]["snippet"]["textDisplay"]
            comments.append(comment)

        # Fetch next page of comments if available
        request = youtube.commentThreads().list_next(request, response)

    return comments[:max_comments]  # Ensure we do not exceed max_comments


###  Main Script Execution
if __name__ == "__main__":
    # Ask for YouTube Link
    video_url = input(" Paste YouTube video URL: ").strip()

    # Extract Video ID from URL
    if "v=" in video_url:
        video_id = video_url.split("v=")[1].split("&")[0]
    elif "youtu.be/" in video_url:
        video_id = video_url.split("youtu.be/")[1].split("?")[0]
    else:
        print(" Invalid YouTube URL format. Please enter a valid link.")
        exit(1)

    # Ask user how many comments to fetch
    try:
        max_comments = int(input("🔢 Enter the number of comments to fetch (max 5000 recommended): "))
        if max_comments <= 0:
            raise ValueError
    except ValueError:
        print(" Invalid input. Using default (100) comments.")
        max_comments = 100

    # Ask user if they want "top" or "latest" comments
    sort_option = input(" Fetch top comments or latest comments? (Enter 'top' or 'latest'): ").strip().lower()
    sort_by = "relevance" if sort_option == "top" else "time"

    # Train Sentiment Model
    model, vectorizer = train_sentiment_model()

    # Fetch Comments
    comments = get_youtube_comments(video_id, max_comments, sort_by)

    # Fetch and Analyze Video Transcript
    video_transcript = get_video_transcript(video_id)
    video_sentiment = predict_sentiment(video_transcript, model, vectorizer) if video_transcript else "unknown"

    # Save Comments and Video Sentiment to CSV
    df = pd.DataFrame(comments, columns=["comment"])
    df["video_sentiment"] = video_sentiment  # Add video sentiment column
    df.to_csv("youtube_comments.csv", index=False)

    print(f" YouTube comments and video sentiment saved to `youtube_comments.csv`")
    print(f" Video Sentiment: {video_sentiment}")
    print(f" Total Comments Fetched: {len(comments)}")
