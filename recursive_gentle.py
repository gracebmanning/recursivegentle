from align import align_with_gentle_core
import subprocess  # for ffmpeg
import os


# Helper to run ffmpeg
def extract_audio_segment(original_audio, segment_start, segment_end, output_path):
    # Ensure segment_start < segment_end and within bounds
    if segment_start >= segment_end:
        return False
    try:
        # Use -nostdin to prevent ffmpeg from hanging if it expects input
        command = [
            'ffmpeg', '-nostdin', '-i', original_audio,
            '-ss', str(segment_start),
            '-to', str(segment_end),
            '-c', 'copy', output_path
        ]
        subprocess.run(command, check=True,
                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
        return True
    except subprocess.CalledProcessError as e:
        print(f"ffmpeg error: {e.stderr.decode()}")
        return False
    except FileNotFoundError:
        print("ffmpeg not found. Please ensure it's installed and in your PATH.")
        return False


# Main Recursive Function
def recursive_gentle_align(original_audio_path, full_transcript_words, current_audio_segment_path,
                           segment_transcript_words, segment_offset_in_original, recursion_depth=0, max_depth=3):

    final_aligned_words_for_segment = []  # Words aligned in this specific call

    if not segment_transcript_words or recursion_depth > max_depth:
        # Base case: no words to align, or too deep in recursion
        # Return unaligned words with their original text and no timestamps, or some placeholder
        unaligned_output = []
        for word_obj in segment_transcript_words:  # Assuming segment_transcript_words are objects/dicts
            unaligned_output.append(
                {"word": word_obj['text'], "original_index": word_obj['original_index'], "start": None, "end": None, "case": "recursion_failed"})
        return unaligned_output

    # --- 1. Align the current segment ---
    # (Need to adapt your Gentle calling mechanism or script)
    # For now, imagine a function that takes audio path and list of words, returns Gentle's word list
    # This might involve writing segment_transcript_words to a temporary .txt file

    temp_transcript_path = f"temp_transcript_{recursion_depth}_{hash(tuple(w['text'] for w in segment_transcript_words))}.txt"
    with open(temp_transcript_path, 'w') as f:
        f.write(" ".join([w['text'] for w in segment_transcript_words]))

    # This is a placeholder for how you call Gentle and get results
    # You'll need to adapt your existing `align_with_gentle.py` logic into a callable function
    # For example, gentle_results_json = call_gentle_api(current_audio_segment_path, temp_transcript_path)
    # For this example, let's assume gentle_word_list is the list of word_info dicts
    print(
        f"Aligning (depth {recursion_depth}): {current_audio_segment_path} with '{' '.join([w['text'] for w in segment_transcript_words])}'")
    # *** This is where you'd call your Gentle alignment logic for the current_audio_segment_path and temp_transcript_path ***
    # gentle_word_list = your_gentle_interaction_function(current_audio_segment_path, temp_transcript_path)
    gentle_word_list = []  # Placeholder - populate this with Gentle's output for the segment

    # (Mocking Gentle's output for demonstration; replace with actual call)
    # Example: if current_audio_segment_path == "segment1.wav": gentle_word_list = [{'word':'hello', 'case':'success', 'start':0.1, 'end':0.5}, ...]
    # You need to implement the actual call to Gentle here.

    os.remove(temp_transcript_path)  # Clean up temp transcript

    # Map Gentle's output words back to our segment_transcript_words by index/order
    # Gentle returns words it found. We need to see which of our *input* segment_transcript_words were aligned.
    aligned_indices_in_segment = set()
    temp_results_this_pass = []  # store results from *this* gentle call before recursion

    # This mapping is simplistic and assumes Gentle returns words in order and matches input.
    # Gentle's actual output for 'transcript' and 'words' needs careful handling.
    # The 'words' list from Gentle contains info about aligned words.
    # You need to associate these back to your `segment_transcript_words`.
    # For now, let's assume `gentle_word_list` is structured and can be mapped.

    idx_gentle = 0
    for i, expected_word_obj in enumerate(segment_transcript_words):
        word_data_from_gentle = None
        if idx_gentle < len(gentle_word_list):
            # Simplistic matching: Gentle often returns the word from the transcript.
            # A more robust match might be needed if Gentle alters words (e.g. case)
            # or if it inserts/deletes words not in the transcript.
            # For forced alignment, it should mostly stick to the transcript words.
            g_word_info = gentle_word_list[idx_gentle]
            if g_word_info['word'].lower() == expected_word_obj['text'].lower():  # Basic check
                if g_word_info['case'] == 'success':
                    word_data_from_gentle = {
                        # Use original text casing
                        "word": expected_word_obj['text'],
                        "original_index": expected_word_obj['original_index'],
                        "start": g_word_info['start'] + segment_offset_in_original,
                        # "end": g_word_info['end'] + segment_offset_in_original, # If you need end times
                        "case": "success"
                    }
                    final_aligned_words_for_segment.append(
                        word_data_from_gentle)
                    aligned_indices_in_segment.add(i)
                idx_gentle += 1  # Move to next Gentle word only if matched conceptually
            else:  # Gentle might have skipped a word or reported an <unk>
                # This part needs more robust handling based on Gentle's output structure for failed words within a segment
                final_aligned_words_for_segment.append({
                    "word": expected_word_obj['text'],
                    "original_index": expected_word_obj['original_index'],
                    "start": None,  # "end": None,
                    # Get case if available
                    "case": g_word_info.get('case', 'failed_in_segment')
                })
                # If Gentle tried but failed this specific word
                if g_word_info['case'] != 'success' and g_word_info['word'] == expected_word_obj['text']:
                    idx_gentle += 1

        # If word wasn't processed by Gentle or failed
        if not word_data_from_gentle and i not in aligned_indices_in_segment:
            final_aligned_words_for_segment.append({
                "word": expected_word_obj['text'],
                "original_index": expected_word_obj['original_index'],
                "start": None,  # "end": None,
                "case": "not_processed_by_gentle_in_segment"
            })

    # --- 2. Identify new sub-gaps within this segment for further recursion ---
    current_sub_gap_words = []
    # Relative to current_audio_segment_path
    last_successful_word_end_time_in_segment = 0.0

    # Iterate over results of *this* pass
    for i, word_obj_info in enumerate(final_aligned_words_for_segment):
        # The input word for this position
        expected_segment_word_obj = segment_transcript_words[i]

        if word_obj_info['case'] == 'success':
            if current_sub_gap_words:
                # Gap ended. Process it.
                # Determine audio boundaries for this sub_gap
                sub_gap_start_time_in_segment = last_successful_word_end_time_in_segment
                # word_obj_info['start'] is already offset. We need local start for ffmpeg.
                sub_gap_end_time_in_segment = (
                    word_obj_info['start'] - segment_offset_in_original) if word_obj_info['start'] is not None else segment_duration  # (Need segment_duration)

                # Create new temp audio for this sub_gap
                sub_segment_path = f"temp_sub_segment_{recursion_depth}_{i}.wav"
                if extract_audio_segment(current_audio_segment_path, sub_gap_start_time_in_segment, sub_gap_end_time_in_segment, sub_segment_path):
                    # Recursive call
                    recursive_results = recursive_gentle_align(
                        original_audio_path, full_transcript_words, sub_segment_path,
                        current_sub_gap_words,  # List of word objects for the sub-gap
                        segment_offset_in_original + sub_gap_start_time_in_segment,  # New offset
                        recursion_depth + 1, max_depth
                    )
                    # Replace the placeholders for the sub_gap words in final_aligned_words_for_segment with recursive_results
                    # This requires careful list manipulation or building a new list.
                    # For simplicity, let's assume we collect all results and merge later.
                    # For now, just extend:
                    # final_aligned_words_for_segment.extend(recursive_results) # This is not quite right for replacing.
                    # Instead, it's better to build up the results list carefully.

                    # This part is tricky: you need to insert the recursive_results back into the correct place
                    # in final_aligned_words_for_segment, replacing the unaligned placeholders from current_sub_gap_words.
                    # For now, we're just collecting all attempts. A final merge step would be needed.

                    os.remove(sub_segment_path)
                current_sub_gap_words = []

            # Update last successful word end time (local to current segment)
            # last_successful_word_end_time_in_segment = word_obj_info['end'] - segment_offset_in_original if word_obj_info.get('end') is not None else some_default
            # If not using 'end' times, this boundary definition needs care.
            # Perhaps it's better to use the start time of the current successful word as the end of the gap.

        else:  # Word was not successfully aligned in this pass
            # Add the original word object
            current_sub_gap_words.append(expected_segment_word_obj)

        # Update last_successful_word_end_time_in_segment based on word_obj_info if it was successful.
        # If word_obj_info['case'] == 'success' and 'end' in word_obj_info and word_obj_info['end'] is not None:
        #    last_successful_word_end_time_in_segment = word_obj_info['end'] - segment_offset_in_original
        # If you don't have end times, the end of the audio for the gap is the start of the next successfully aligned word.

    # Handle any trailing sub-gap at the end of the segment
    if current_sub_gap_words:
        sub_gap_start_time_in_segment = last_successful_word_end_time_in_segment
        # segment_duration is duration of current_audio_segment_path
        # sub_gap_end_time_in_segment = get_duration(current_audio_segment_path)
        # ... similar recursive call as above ...

    # This will be a mix of successfully aligned words and placeholders/failures from this level
    return final_aligned_words_for_segment


# --- Wrapper to start the process ---
def run_recursive_gentle_on_song(original_audio_path, original_transcript_text):
    # List of {"text": "word", "original_index": i}
    full_transcript_words_list = []
    for i, word_text in enumerate(original_transcript_text.split()):
        full_transcript_words_list.append(
            {"text": word_text, "original_index": i})

    # Initial call is on the whole audio, with offset 0
    all_aligned_results = recursive_gentle_align(
        original_audio_path,
        full_transcript_words_list,  # Pass the structured list
        original_audio_path,        # Current segment is the whole audio
        full_transcript_words_list,  # Current transcript is the full transcript
        0.0,                        # Initial offset is 0
        recursion_depth=0
    )

    # Post-processing:
    # The all_aligned_results can be a flat list if structured correctly, or may need merging.
    # Sort by original_index to reconstruct the full transcript.
    # Filter out/handle words that remained unaligned.
    final_output = [None] * len(full_transcript_words_list)
    for res in all_aligned_results:
        if res and res.get('original_index') is not None:  # Check if res is valid
            # If multiple results for the same index due to recursion structure, prioritize successful ones
            if final_output[res['original_index']] is None or \
               (res['case'] == 'success' and final_output[res['original_index']]['case'] != 'success'):
                final_output[res['original_index']] = res

    return [item for item in final_output if item is not None]  # Cleaned list
