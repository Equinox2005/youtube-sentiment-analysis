import pandas as pd
from sklearn.feature_extraction.text import CountVectorizer
from sklearn.naive_bayes import MultinomialNB
import os

###  Load Sentiment140 Dataset
def load_sentiment140():
    dataset_path = "sentiment140.csv"
    if not os.path.exists(dataset_path):
        print(f"Error: {dataset_path} not found. Please download Sentiment140 dataset.")
        exit(1)

    df = pd.read_csv(dataset_path, encoding="latin1", usecols=[0, 5], names=["sentiment", "text"])
    df["sentiment"] = df["sentiment"].replace({0: "neg", 4: "pos"})
    return df

###  Train Sentiment Model
def train_sentiment_model():
    df = load_sentiment140()
    vectorizer = CountVectorizer(max_features=2000)
    X = vectorizer.fit_transform(df["text"])
    y = df["sentiment"]
    model = MultinomialNB()
    model.fit(X, y)
    return model, vectorizer

###  Predict Sentiment
def predict_sentiment(text, model, vectorizer):
    text_vector = vectorizer.transform([text])
    prediction = model.predict(text_vector)
    return prediction[0]

###  Analyze YouTube Comments
def analyze_youtube_comments():
    model, vectorizer = train_sentiment_model()

    # Load YouTube comments and video sentiment
    comments_df = pd.read_csv("youtube_comments.csv")
    comments = comments_df["comment"].tolist()
    video_sentiment = comments_df["video_sentiment"].iloc[0]

    def classify_comment_agreement(comment):
        comment_sentiment = predict_sentiment(comment, model, vectorizer)
        if video_sentiment == "unknown":
            return "unknown"
        return "agree" if comment_sentiment == video_sentiment else "disagree"

    agreements = [classify_comment_agreement(comment) for comment in comments]
    agree_count = agreements.count("agree")
    disagree_count = agreements.count("disagree")

    print(f"📊 **Sentiment Analysis Results:**")
    print(f"Total Comments Analyzed: {len(comments)}")
    print(f"👍 Agreeing Comments: {agree_count} ({(agree_count / len(comments)) * 100:.2f}%)")
    print(f"👎 Disagreeing Comments: {disagree_count} ({(disagree_count / len(comments)) * 100:.2f}%)")

if __name__ == "__main__":
    analyze_youtube_comments()
