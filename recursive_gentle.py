import subprocess
import os
import json
import tempfile  # For creating temporary transcript files
import shutil  # For cleaning up temporary directories

# Assuming gentle_client.py is in the same directory or your Python path
from align import align_with_gentle_core

# --- Configuration ---
MAX_RECURSION_DEPTH = 2  # To prevent infinite loops, adjust as needed
MIN_WORDS_FOR_RECURSION = 2  # Don't recurse on very small gaps if not desired


def get_audio_duration(audio_file_path):
    """Gets the duration of an audio file using ffprobe."""
    try:
        command = [
            'ffprobe', '-v', 'error', '-show_entries', 'format=duration',
            '-of', 'default=noprint_wrappers=1:nokey=1', audio_file_path
        ]
        result = subprocess.run(
            command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, check=True, text=True)
        return float(result.stdout.strip())
    except subprocess.CalledProcessError as e:
        print(f"Error getting duration with ffprobe: {e.stderr}")
        return None
    except FileNotFoundError:
        print("ffprobe not found. Please ensure ffmpeg (which includes ffprobe) is installed and in your PATH.")
        return None


def extract_audio_segment(original_audio_path, segment_start_time, segment_end_time, output_segment_path):
    """
    Extracts a segment from an audio file using ffmpeg.
    Ensures start_time < end_time and handles minor floating point inaccuracies for ffmpeg.
    """
    if segment_start_time >= segment_end_time - 0.01:  # segment must have some duration
        # If segment is too short or invalid, don't attempt extraction
        print(
            f"Warning (extract_audio): Segment too short or invalid. Start: {segment_start_time}, End: {segment_end_time}")
        return False
    try:
        # Use -nostdin to prevent ffmpeg from hanging if it expects input
        command = [
            'ffmpeg', '-nostdin', '-i', original_audio_path,
            '-ss', str(segment_start_time),
            '-to', str(segment_end_time),
            '-c', 'copy', '-y',  # -y overwrites output file if it exists
            output_segment_path
        ]
        # print(f"Executing ffmpeg: {' '.join(command)}") # For debugging
        subprocess.run(command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        print(
            f"ffmpeg error extracting segment '{output_segment_path}': {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("ffmpeg not found. Please ensure it's installed and in your PATH.")
        return False


def create_temp_transcript_file(words_list, base_filename="segment_transcript"):
    """Creates a temporary transcript file from a list of word strings."""
    try:
        # Create a temporary file that is automatically cleaned up
        # Suffix helps identify the file, prefix helps group them if needed
        temp_file = tempfile.NamedTemporaryFile(
            mode='w+', delete=False, encoding='utf-8', suffix='.txt', prefix=f"{base_filename}_")
        temp_file.write(" ".join(words_list))
        temp_file_path = temp_file.name
        temp_file.close()  # Close the file so Gentle (or other processes) can access it
        return temp_file_path
    except Exception as e:
        print(f"Error creating temporary transcript file: {e}")
        return None


def recursive_gentle_align(
    current_audio_path,
    # List of dicts: [{'text': 'word', 'original_global_index': N}, ...]
    transcript_word_objects,
    # The start time of current_audio_path relative to the original full audio
    current_segment_audio_offset,
    recursion_depth=0
):
    """
    Performs alignment, identifies unaligned regions, and recursively calls itself.

    Args:
        current_audio_path (str): Path to the audio file for the current segment.
        transcript_word_objects (list): List of word objects for this segment.
                                     Each object is a dict: {'text': str, 'original_global_index': int}
        current_segment_audio_offset (float): Start time of current_audio_path in the original full audio's timeline.
        recursion_depth (int): Current depth of recursion.

    Returns:
        list: A list of word alignment result objects. Each object includes:
              'word' (str): The text of the word.
              'original_global_index' (int): Index in the original full transcript.
              'start' (float/None): Absolute start time in the original audio.
              'end' (float/None): Absolute end time in the original audio.
              'case' (str): Alignment status (e.g., 'success', 'failed_recursion').
    """
    print(f"{'  '*recursion_depth}RecursiveGentle (Depth {recursion_depth}): Aligning '{os.path.basename(current_audio_path)}' "
          f"({len(transcript_word_objects)} words) with offset {current_segment_audio_offset:.2f}s")

    final_results_for_this_segment = []

    if not transcript_word_objects:
        print(
            f"{'  '*recursion_depth}No words in transcript for this segment. Returning.")
        return []

    if recursion_depth > MAX_RECURSION_DEPTH:
        print(f"{'  '*recursion_depth}Max recursion depth ({MAX_RECURSION_DEPTH}) reached. Marking remaining as failed.")
        for i, word_obj in enumerate(transcript_word_objects):
            final_results_for_this_segment.append({
                'word': word_obj['text'],
                'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_max_depth'
            })
        return final_results_for_this_segment

    # 1. Create a temporary transcript file for the current segment
    current_transcript_text_list = [wo['text']
                                    for wo in transcript_word_objects]
    temp_segment_transcript_path = create_temp_transcript_file(
        current_transcript_text_list, f"depth{recursion_depth}")

    if not temp_segment_transcript_path:
        print(
            f"{'  '*recursion_depth}Failed to create temp transcript. Marking as failed.")
        for i, word_obj in enumerate(transcript_word_objects):
            final_results_for_this_segment.append({
                'word': word_obj['text'],
                'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_temp_transcript_creation'
            })
        return final_results_for_this_segment

    # 2. Align the current audio segment with its transcript using align_with_gentle_core
    # gentle_output_words is a list of dicts from Gentle (like the sample you provided)
    gentle_output_words = align_with_gentle_core(
        current_audio_path, temp_segment_transcript_path)
    # Clean up the temporary transcript file
    os.remove(temp_segment_transcript_path)

    if not gentle_output_words:
        print(
            f"{'  '*recursion_depth}Gentle core returned no words or failed. Marking segment as failed.")
        # This means Gentle failed entirely for this segment. Mark all words in this segment as failed.
        for i, word_obj in enumerate(transcript_word_objects):
            final_results_for_this_segment.append({
                'word': word_obj['text'],
                'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_gentle_core_call'
            })
        return final_results_for_this_segment

    # 3. Process Gentle's output for this segment
    # We need to map Gentle's output (which is ordered by its processing of the temp_segment_transcript)
    # back to our transcript_word_objects. Gentle's output list should correspond fairly directly
    # to the words in the transcript it was given, including entries for unaligned words.

    # current_word_idx_in_gentle_output = 0 # To iterate through gentle_output_words
    # current_unaligned_gap_words = [] # List of {'text': ..., 'original_global_index': ...}
    # last_successful_word_end_time_local = 0.0 # Relative to current_audio_path

    # This initial processing will just collect results and identify gaps.
    # A more sophisticated approach will directly build the final_results_for_this_segment
    # and make recursive calls as it iterates. Let's try a more direct approach.

    processed_gentle_idx = 0
    temp_unaligned_streak = []  # Stores word_objects from transcript_word_objects

    for i, current_transcript_word_obj in enumerate(transcript_word_objects):
        # Try to find the corresponding word in Gentle's output.
        # Gentle's output list should align with the input transcript word order.
        if processed_gentle_idx < len(gentle_output_words):
            gentle_word_info = gentle_output_words[processed_gentle_idx]

            # Sanity check: Does gentle_word_info['word'] roughly match current_transcript_word_obj['text']?
            # Gentle might normalize case or punctuation. For now, we assume the order is primary.
            # A more robust mapping might use `startOffset` if available and reliable across calls.

            if gentle_word_info['case'] == 'success':
                # --- Successful alignment ---
                if temp_unaligned_streak:
                    # Process the ended unaligned streak recursively
                    print(
                        f"{'  '*recursion_depth}---> Found unaligned streak of {len(temp_unaligned_streak)} words to process recursively.")
                    # TODO: Define audio boundaries for this streak and make recursive call
                    # For now, let's just mark them as 'pending_recursion' for clarity
                    for unaligned_wo in temp_unaligned_streak:
                        final_results_for_this_segment.append({
                            'word': unaligned_wo['text'], 'original_global_index': unaligned_wo['original_global_index'],
                            'start': None, 'end': None, 'case': 'placeholder_for_recursion_output'
                        })
                    temp_unaligned_streak = []

                final_results_for_this_segment.append({
                    # Use our original casing
                    'word': current_transcript_word_obj['text'],
                    'original_global_index': current_transcript_word_obj['original_global_index'],
                    'start': gentle_word_info['start'] + current_segment_audio_offset,
                    'end': gentle_word_info['end'] + current_segment_audio_offset,
                    'case': 'success'
                })
                # last_successful_word_end_time_local = gentle_word_info['end']
            else:
                # --- Word not successfully aligned by Gentle in this pass ---
                temp_unaligned_streak.append(current_transcript_word_obj)
            processed_gentle_idx += 1
        else:
            # Ran out of Gentle words but still have transcript words (should ideally not happen if Gentle processes all)
            temp_unaligned_streak.append(current_transcript_word_obj)

    # Handle any trailing unaligned streak after the loop
    if temp_unaligned_streak:
        print(f"{'  '*recursion_depth}---> Found TRAILING unaligned streak of {len(temp_unaligned_streak)} words to process.")
        # TODO: Define audio boundaries and recurse
        for unaligned_wo in temp_unaligned_streak:
            final_results_for_this_segment.append({
                'word': unaligned_wo['text'], 'original_global_index': unaligned_wo['original_global_index'],
                'start': None, 'end': None, 'case': 'placeholder_for_recursion_output_trailing'
            })

    # At this point, final_results_for_this_segment contains successful alignments
    # from this level, and placeholders for where recursive results should go.
    # The next step is to implement the actual recursion logic within this loop/structure.

    # For now, this function only does one level of processing and identifies where recursion *would* go.
    # The actual recursive call logic is still needed.
    print(f"{'  '*recursion_depth}Finished processing segment. Results (this level): {len(final_results_for_this_segment)} items.")
    return final_results_for_this_segment


def process_song_recursively(original_audio_path, original_transcript_text):
    """
    Main wrapper to start the recursive alignment process for a song.
    """
    # Prepare initial transcript word objects
    # Each word needs its original text and its index in the full transcript
    original_words = original_transcript_text.strip().split()
    if not original_words:
        print("Error: Original transcript text is empty.")
        return []

    initial_transcript_word_objects = []
    for i, word_text in enumerate(original_words):
        initial_transcript_word_objects.append(
            {'text': word_text, 'original_global_index': i})

    # Make a temporary directory for all segments for this run (optional, for inspection)
    # base_temp_dir = tempfile.mkdtemp(prefix="rec_gentle_")
    # print(f"Using temporary directory: {base_temp_dir}")

    # Initial call to the recursive function
    all_aligned_word_data = recursive_gentle_align(
        current_audio_path=original_audio_path,
        transcript_word_objects=initial_transcript_word_objects,
        current_segment_audio_offset=0.0,  # Offset for the full audio is 0
        recursion_depth=0
    )

    # The output `all_aligned_word_data` will be a flat list if recursion is fully implemented
    # to replace placeholders. For now, it will have placeholders.
    # We need to sort by original_global_index to ensure correct order.
    all_aligned_word_data.sort(key=lambda x: x['original_global_index'])

    # Clean up temporary directory (if created)
    # if os.path.exists(base_temp_dir):
    #     shutil.rmtree(base_temp_dir)

    return all_aligned_word_data


# --- Main execution block ---
if __name__ == '__main__':
    print("Starting Recursive Gentle Aligner...")

    # Configure paths (MAKE SURE THESE FILES EXIST)
    # Using the example from your output
    # You should have a WAV file and a plain text transcript file.
    # The transcript should contain the words:
    # "It's getting late have you seen my mates Ma tell me when the boys get here It's seven o'clock and"
    # (or at least the part your JSON sample covers)
    test_audio_file = "C:/Projects/gentle_files/saturdayNight/saturday-night-vocals-only.mp3"
    test_transcript_file = "C:/Projects/gentle_files/saturdayNight/SaturdayNightsAlright-lyrics.txt"
    output_json_recursive = "C:/Projects/gentle_files/recursivegentle/output/recursive_alignment_output.json"

    if not os.path.exists(test_audio_file):
        print(f"ERROR: Test audio file not found: {test_audio_file}")
        exit()
    if not os.path.exists(test_transcript_file):
        print(f"ERROR: Test transcript file not found: {test_transcript_file}")
        exit()

    with open(test_transcript_file, 'r', encoding='utf-8') as f:
        transcript_content = f.read()

    final_results = process_song_recursively(
        test_audio_file, transcript_content)

    print("\n--- Final Recursive Alignment Results ---")
    if final_results:
        for res in final_results:
            status = f"Start: {res['start']:.2f}, End: {res['end']:.2f}" if res['case'] == 'success' else f"Status: {res['case']}"
            print(
                f"  Index {res['original_global_index']:03d} | Word: '{res['word']}' | {status}")

        # Save to JSON
        output_dir = os.path.dirname(output_json_recursive)
        if not os.path.exists(output_dir):
            os.makedirs(output_dir)
        with open(output_json_recursive, 'w', encoding='utf-8') as f:
            json.dump(final_results, f, indent=4)
        print(
            f"\nFull recursive alignment results saved to: {output_json_recursive}")
    else:
        print("No alignment results produced.")
