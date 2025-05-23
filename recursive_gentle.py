import subprocess
import os
import json
import tempfile  # For creating temporary transcript files
import shutil  # For cleaning up temporary directories

# Assuming gentle_client.py is in the same directory or your Python path
from align import align_with_gentle_core

# --- Configuration ---
MAX_RECURSION_DEPTH = 3  # To prevent infinite loops, adjust as needed
MIN_WORDS_FOR_RECURSION = 2  # Don't recurse on very small gaps if not desired


def normalize_word(text, characters_to_strip=",."):
    if not isinstance(text, str):  # Should not happen with Gentle output but good check
        return ""
    return text.lower().rstrip(characters_to_strip)


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
    transcript_word_objects,
    current_segment_audio_offset,
    recursion_depth=0,
    # Add base_temp_dir for managing sub-clips
    base_temp_dir=None
):
    print(f"{'  '*recursion_depth}RecursiveGentle (Depth {recursion_depth}): Aligning '{os.path.basename(current_audio_path)}' "
          f"({len(transcript_word_objects)} words) with offset {current_segment_audio_offset:.2f}s")

    # This list will store the final results for this segment, including results from recursion
    compiled_results_for_this_segment = []

    if not transcript_word_objects:
        print(
            f"{'  '*recursion_depth}No words in transcript for this segment. Returning.")
        return []

    if recursion_depth > MAX_RECURSION_DEPTH:
        print(f"{'  '*recursion_depth}Max recursion depth ({MAX_RECURSION_DEPTH}) reached. Marking remaining as failed.")
        for word_obj in transcript_word_objects:
            compiled_results_for_this_segment.append({
                'word': word_obj['text'],
                'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_max_depth'
            })
        return compiled_results_for_this_segment

    current_transcript_text_list = [wo['text']
                                    for wo in transcript_word_objects]
    temp_segment_transcript_path = create_temp_transcript_file(
        current_transcript_text_list,
        # Slightly more unique name
        f"depth{recursion_depth}_seg{hash(current_audio_path.split('.')[0])}"
    )

    if not temp_segment_transcript_path:
        # Handle failure (mark words and return)
        for word_obj in transcript_word_objects:
            compiled_results_for_this_segment.append({
                'word': word_obj['text'], 'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_temp_transcript_creation'
            })
        return compiled_results_for_this_segment

    gentle_output_words = align_with_gentle_core(
        current_audio_path, temp_segment_transcript_path)
    try:
        os.remove(temp_segment_transcript_path)
    except OSError as e:
        print(f"{'  '*recursion_depth}Warning: Could not remove temp transcript {temp_segment_transcript_path}: {e}")

    if not gentle_output_words:
        # Handle Gentle failure for the whole segment
        for word_obj in transcript_word_objects:
            compiled_results_for_this_segment.append({
                'word': word_obj['text'], 'original_global_index': word_obj['original_global_index'],
                'start': None, 'end': None, 'case': 'failed_gentle_core_call_no_output'
            })
        return compiled_results_for_this_segment

    # --- Iterate through the transcript words and Gentle's output for this segment ---
    transcript_idx = 0
    gentle_idx = 0
    last_successful_word_end_time_local = 0.0  # Relative to current_audio_path

    while transcript_idx < len(transcript_word_objects):
        current_word_obj = transcript_word_objects[transcript_idx]

        if gentle_idx < len(gentle_output_words):
            gentle_word_info = gentle_output_words[gentle_idx]

            # Normalize both for comparison:
            normalized_gentle_word = normalize_word(gentle_word_info['word'])
            normalized_transcript_word = normalize_word(
                current_word_obj['text'])

            if normalized_gentle_word == normalized_transcript_word:
                if gentle_word_info['case'] == 'success':
                    # Successfully aligned word
                    compiled_results_for_this_segment.append({
                        # Use original casing
                        'word': current_word_obj['text'],
                        'original_global_index': current_word_obj['original_global_index'],
                        'start': gentle_word_info['start'] + current_segment_audio_offset,
                        'end': gentle_word_info['end'] + current_segment_audio_offset,
                        'case': 'success'
                    })
                    last_successful_word_end_time_local = gentle_word_info['end']
                    transcript_idx += 1
                    gentle_idx += 1
                else:
                    # Word found by Gentle but not aligned (e.g., "not-found-in-audio")
                    # This is the start of a potential unaligned streak
                    unaligned_streak_transcript_objects = []
                    streak_start_transcript_idx = transcript_idx

                    # Collect the streak of unaligned words
                    while transcript_idx < len(transcript_word_objects) and \
                            gentle_idx < len(gentle_output_words) and \
                            gentle_output_words[gentle_idx]['word'].lower() == transcript_word_objects[transcript_idx]['text'].lower() and \
                            gentle_output_words[gentle_idx]['case'] != 'success':
                        unaligned_streak_transcript_objects.append(
                            transcript_word_objects[transcript_idx])
                        transcript_idx += 1
                        gentle_idx += 1  # Move gentle_idx along with transcript_idx for these failed words

                    # Determine audio boundaries for this streak
                    gap_start_time_local = last_successful_word_end_time_local
                    gap_end_time_local = -1.0

                    if transcript_idx < len(transcript_word_objects) and \
                       gentle_idx < len(gentle_output_words) and \
                       gentle_output_words[gentle_idx]['word'].lower() == transcript_word_objects[transcript_idx]['text'].lower() and \
                       gentle_output_words[gentle_idx]['case'] == 'success':
                        # Streak is followed by a successfully aligned word
                        gap_end_time_local = gentle_output_words[gentle_idx]['start']
                    else:
                        # Streak goes to the end of the current segment or Gentle output mismatch
                        segment_duration = get_audio_duration(
                            current_audio_path)
                        gap_end_time_local = segment_duration if segment_duration is not None else last_successful_word_end_time_local + \
                            10.0  # Fallback duration if ffprobe fails

                    print(
                        f"{'  '*(recursion_depth+1)}Identified unaligned streak: {[wo['text'] for wo in unaligned_streak_transcript_objects]}")
                    print(
                        f"{'  '*(recursion_depth+1)}Audio for streak: local start={gap_start_time_local:.2f}, local end={gap_end_time_local:.2f}")

                    if len(unaligned_streak_transcript_objects) >= MIN_WORDS_FOR_RECURSION and \
                       gap_end_time_local > gap_start_time_local + 0.1:  # Ensure segment has some duration
                        # --- Attempt Recursive Call ---
                        temp_sub_clip_filename = f"depth{recursion_depth+1}_seg{hash(current_word_obj['text'])}_{unaligned_streak_transcript_objects[0]['original_global_index']}.wav"

                        # Use base_temp_dir if provided, otherwise use current dir (less clean)
                        sub_clip_dir = base_temp_dir if base_temp_dir else os.path.dirname(
                            current_audio_path)
                        if base_temp_dir and not os.path.exists(base_temp_dir):
                            os.makedirs(base_temp_dir)
                        temp_sub_clip_path = os.path.join(
                            sub_clip_dir, temp_sub_clip_filename)

                        if extract_audio_segment(current_audio_path, gap_start_time_local, gap_end_time_local, temp_sub_clip_path):
                            recursive_results = recursive_gentle_align(
                                temp_sub_clip_path,
                                unaligned_streak_transcript_objects,
                                current_segment_audio_offset + gap_start_time_local,  # New absolute offset
                                recursion_depth + 1,
                                base_temp_dir  # Pass along the temp dir
                            )
                            compiled_results_for_this_segment.extend(
                                recursive_results)
                            try:
                                os.remove(temp_sub_clip_path)
                            except OSError as e:
                                print(
                                    f"{'  '*(recursion_depth+1)}Warning: Could not remove temp sub-clip {temp_sub_clip_path}: {e}")
                        else:
                            print(
                                f"{'  '*(recursion_depth+1)}Failed to extract audio for streak. Marking as failed.")
                            for wo in unaligned_streak_transcript_objects:
                                compiled_results_for_this_segment.append({
                                    'word': wo['text'], 'original_global_index': wo['original_global_index'],
                                    'start': None, 'end': None, 'case': 'failed_ffmpeg_extraction'
                                })
                    else:
                        # Streak too short for recursion or invalid time segment
                        reason = 'failed_min_words_for_recursion'
                        if not (gap_end_time_local > gap_start_time_local + 0.1):
                            reason = 'failed_invalid_gap_time'
                        for wo in unaligned_streak_transcript_objects:
                            compiled_results_for_this_segment.append({
                                'word': wo['text'], 'original_global_index': wo['original_global_index'],
                                'start': None, 'end': None, 'case': reason
                            })
                    # The transcript_idx has already been advanced past the streak by the inner while loop.
                    # gentle_idx has also been advanced.
            else:
                # Mismatch between Gentle's word and transcript_word_object word.
                # This indicates a potential desync or severe alteration by Gentle.
                # For forced alignment, this should be rare if the transcript is accurate.
                print(
                    f"{'  '*recursion_depth}Warning: Mismatch or desync. Gentle: '{gentle_word_info['word']}', Transcript: '{current_word_obj['text']}'. Marking transcript word as error.")
                compiled_results_for_this_segment.append({
                    'word': current_word_obj['text'], 'original_global_index': current_word_obj['original_global_index'],
                    'start': None, 'end': None, 'case': 'error_transcript_gentle_desync'
                })
                transcript_idx += 1
                # We might need to advance gentle_idx as well, or attempt to re-sync.
                # For now, advance gentle_idx to try and recover.
                gentle_idx += 1

        else:  # Ran out of Gentle output words, but still have transcript words for this segment
            print(f"{'  '*recursion_depth}Warning: Ran out of Gentle output words; transcript segment may be longer. Remaining words marked as unaligned.")
            # This part will handle any remaining transcript words if Gentle's output was shorter.
            # These are effectively a trailing unaligned streak.
            trailing_streak_objects = transcript_word_objects[transcript_idx:]
            gap_start_time_local = last_successful_word_end_time_local
            segment_duration = get_audio_duration(current_audio_path)
            gap_end_time_local = segment_duration if segment_duration is not None else last_successful_word_end_time_local + 10.0  # Fallback

            if len(trailing_streak_objects) >= MIN_WORDS_FOR_RECURSION and \
               recursion_depth < MAX_RECURSION_DEPTH and \
               gap_end_time_local > gap_start_time_local + 0.1:

                temp_sub_clip_filename = f"depth{recursion_depth+1}_seg_trailing_{hash(current_word_obj['text'])}_{trailing_streak_objects[0]['original_global_index']}.wav"
                sub_clip_dir = base_temp_dir if base_temp_dir else os.path.dirname(
                    current_audio_path)
                if base_temp_dir and not os.path.exists(base_temp_dir):
                    os.makedirs(base_temp_dir)
                temp_sub_clip_path = os.path.join(
                    sub_clip_dir, temp_sub_clip_filename)

                if extract_audio_segment(current_audio_path, gap_start_time_local, gap_end_time_local, temp_sub_clip_path):
                    recursive_results = recursive_gentle_align(
                        temp_sub_clip_path,
                        trailing_streak_objects,
                        current_segment_audio_offset + gap_start_time_local,
                        recursion_depth + 1,
                        base_temp_dir
                    )
                    compiled_results_for_this_segment.extend(recursive_results)
                    try:
                        os.remove(temp_sub_clip_path)
                    except OSError as e:
                        print(
                            f"{'  '*(recursion_depth+1)}Warning: Could not remove temp sub-clip {temp_sub_clip_path}: {e}")
                else:
                    for wo in trailing_streak_objects:
                        compiled_results_for_this_segment.append({
                            'word': wo['text'], 'original_global_index': wo['original_global_index'],
                            'start': None, 'end': None, 'case': 'failed_ffmpeg_extraction_trailing'
                        })
            else:
                for wo in trailing_streak_objects:
                    compiled_results_for_this_segment.append({
                        'word': wo['text'], 'original_global_index': wo['original_global_index'],
                        'start': None, 'end': None, 'case': 'failed_trailing_streak_no_recursion'
                    })
            break  # All remaining transcript words processed as a trailing streak

    return compiled_results_for_this_segment


def process_song_recursively(original_audio_path, original_transcript_text):
    original_words = original_transcript_text.strip().split()
    if not original_words:
        print("Error: Original transcript text is empty.")
        return []

    initial_transcript_word_objects = [
        {'text': text, 'original_global_index': i} for i, text in enumerate(original_words)]

    # Create a single temporary directory for all sub-clips for this entire run
    run_temp_dir = tempfile.mkdtemp(prefix="rec_gentle_run_")
    print(f"Using temporary directory for audio segments: {run_temp_dir}")

    all_aligned_word_data = recursive_gentle_align(
        current_audio_path=original_audio_path,
        transcript_word_objects=initial_transcript_word_objects,
        current_segment_audio_offset=0.0,
        recursion_depth=0,
        base_temp_dir=run_temp_dir  # Pass the created temp directory
    )

    # Sort by original_global_index to ensure correct order in the final output
    all_aligned_word_data.sort(key=lambda x: x['original_global_index'])

    # Clean up the temporary directory
    try:
        if os.path.exists(run_temp_dir):
            shutil.rmtree(run_temp_dir)
            print(f"Cleaned up temporary directory: {run_temp_dir}")
    except OSError as e:
        print(
            f"Warning: Could not remove temporary directory {run_temp_dir}: {e}")

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
    output_json_recursive = "C:/Projects/gentle_files/recursivegentle/output/recursive_output.json"

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
