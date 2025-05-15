import requests
import json
import os

# Configuration for the Gentle server
GENTLE_SERVER_URL = "http://localhost:8765/transcriptions?async=false"


def align_with_gentle_core(audio_file_path, transcript_file_path):
    """
    Aligns a given audio file with a transcript file using the Gentle server.

    Args:
        audio_file_path (str): The absolute path to the audio file.
        transcript_file_path (str): The absolute path to the transcript text file.

    Returns:
        list: A list of word alignment dictionaries from Gentle if successful,
              e.g., [{'word': 'hello', 'start': 0.5, 'end': 0.9, 'case': 'success', ...}].
              Returns an empty list if alignment fails or no words are found.
    """
    # --- Check if input files exist ---
    if not os.path.exists(audio_file_path):
        print(f"Error (core): Audio file not found at {audio_file_path}")
        return []
    if not os.path.exists(transcript_file_path):
        print(
            f"Error (core): Transcript file not found at {transcript_file_path}")
        return []

    files_to_upload = None
    audio_file_obj = None
    transcript_file_obj = None

    try:
        audio_file_obj = open(audio_file_path, 'rb')
        transcript_file_obj = open(transcript_file_path, 'rb')

        files_to_upload = {
            'audio': (os.path.basename(audio_file_path), audio_file_obj, 'audio/*'),
            'transcript': (os.path.basename(transcript_file_path), transcript_file_obj, 'text/plain')
        }

        print(
            f"Core: Sending alignment request for {os.path.basename(audio_file_path)} and {os.path.basename(transcript_file_path)}...")
        response = requests.post(GENTLE_SERVER_URL, files=files_to_upload)

        # --- Process the response ---
        if response.status_code == 200:
            try:
                alignment_result = response.json()
                return alignment_result.get('words', [])
            except json.JSONDecodeError:
                print(
                    f"Error (core): Could not decode JSON response. Response text: {response.text}")
                return []
        elif response.status_code == 400:
            print(
                f"Error (core): Alignment failed (400). Response: {response.text}")
            return []
        else:
            print(
                f"Error (core): Request failed ({response.status_code}). Response: {response.text}")
            return []

    except requests.exceptions.ConnectionError:
        print(
            f"Error (core): Could not connect to Gentle server at {GENTLE_SERVER_URL}.")
        return []
    except FileNotFoundError as e:
        print(f"Error (core): File not found - {e}")
        return []
    except Exception as e:
        print(f"Error (core): An unexpected error occurred: {e}")
        return []
    finally:
        # --- Close the opened files ---
        if audio_file_obj and not audio_file_obj.closed:
            audio_file_obj.close()
        if transcript_file_obj and not transcript_file_obj.closed:
            transcript_file_obj.close()


if __name__ == '__main__':
    # --- Example Usage for align_with_gentle_core (for testing this file directly) ---
    print("Running test for align_with_gentle_core (gentle_client.py)...")

    # Replace with actual paths to your test files
    # Ensure these files exist and Gentle Docker container is running
    # Or a simpler test file
    example_audio_path = "C:/Users/graci/Downloads/gentle_files/saturdayNight/saturday-night-vocals-only.mp3"
    # Or a simpler test file
    example_transcript_path = "C:/Users/graci/Downloads/gentle_files/saturdayNight/SaturdayNightsAlright-lyrics.txt"
    DUMMY_OUTPUT_JSON_PATH = "/output/dummy_output_align_core"

    if os.path.exists(example_audio_path) and os.path.exists(example_transcript_path):
        print(
            f"\nAttempting to align '{os.path.basename(example_audio_path)}' with '{os.path.basename(example_transcript_path)}'...")
        aligned_words = align_with_gentle_core(
            example_audio_path, example_transcript_path)

        if aligned_words:
            print(
                f"\nSuccessfully aligned {len(aligned_words)} words (first 5 shown):")
            for i, word_info in enumerate(aligned_words):
                if i < 5:  # Print only first 5 for brevity
                    print(
                        f"  Word: {word_info.get('word')}, Start: {word_info.get('start')}, Case: {word_info.get('case')}")
            try:
                with open(DUMMY_OUTPUT_JSON_PATH, 'w') as f:
                    json.dump(aligned_words, f, indent=4)
                print(
                    f"\nFull alignment results saved to {DUMMY_OUTPUT_JSON_PATH}")
            except Exception as e:
                print(f"Error saving dummy output: {e}")
        else:
            print("\nAlignment failed or no words were aligned by gentle_client.py test.")
    else:
        print(
            f"\nTest files not found. Please ensure '{example_audio_path}' and '{example_transcript_path}' exist.")
