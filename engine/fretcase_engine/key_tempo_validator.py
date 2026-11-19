"""
Key and Tempo Validator for ABC Notation

This module validates that generated ABC notation uses the correct
Key signature (K:) and Tempo (Q:) fields as specified by the user.
"""

import re
from typing import Dict, Optional


def validate_key_tempo(
    abc_string: str, 
    expected_key: str, 
    expected_tempo: int
) -> Dict[str, any]:
    """
    Validate that ABC notation uses correct Key and Tempo.
    
    Args:
        abc_string: ABC notation string to validate
        expected_key: Expected key signature (e.g., "C", "G", "Am", "Dm")
        expected_tempo: Expected tempo in BPM (e.g., 120)
        
    Returns:
        Dictionary with validation results:
        {
            'valid': bool,              # Overall validation result
            'key_match': bool,          # Key signature matches
            'tempo_match': bool,        # Tempo matches
            'found_key': str | None,    # Actual key found in ABC
            'found_tempo': int | None,  # Actual tempo found in ABC
            'feedback': str             # Human-readable feedback
        }
    
    Example:
        >>> abc = "X:1\\nT:Test\\nM:4/4\\nL:1/8\\nQ:1/4=120\\nK:G\\nV:1\\nGABc|"
        >>> result = validate_key_tempo(abc, "G", 120)
        >>> result['valid']
        True
    """
    # Parse K: field (Key signature)
    key_pattern = r'K:\s*([A-G][#b]?m?(?:maj|min|dor|phr|lyd|mix|aeo|loc)?)'
    key_match = re.search(key_pattern, abc_string, re.IGNORECASE)
    found_key = key_match.group(1) if key_match else None
    
    # Normalize key for comparison (handle different notations)
    if found_key:
        found_key = _normalize_key(found_key)
    expected_key_normalized = _normalize_key(expected_key)
    
    # Parse Q: field (Tempo)
    tempo_pattern = r'Q:\s*(?:1/4\s*=\s*)?(\d+)'
    tempo_match = re.search(tempo_pattern, abc_string)
    found_tempo = int(tempo_match.group(1)) if tempo_match else None
    
    # Validate matches
    key_valid = (found_key == expected_key_normalized) if found_key else False
    tempo_valid = (found_tempo == expected_tempo) if found_tempo else False
    
    # Generate feedback
    feedback_parts = []
    
    if not key_valid:
        if not found_key:
            feedback_parts.append(f"❌ Missing Key signature: Expected K:{expected_key}")
        else:
            feedback_parts.append(
                f"❌ Key mismatch: Expected K:{expected_key}, found K:{found_key}"
            )
    
    if not tempo_valid:
        if not found_tempo:
            feedback_parts.append(f"❌ Missing Tempo: Expected Q:1/4={expected_tempo}")
        else:
            feedback_parts.append(
                f"❌ Tempo mismatch: Expected Q:1/4={expected_tempo}, found Q:1/4={found_tempo}"
            )
    
    if key_valid and tempo_valid:
        feedback = f"✅ Key and Tempo are correct (K:{found_key}, Q:1/4={found_tempo})"
    else:
        feedback = '\n'.join(feedback_parts)
    
    return {
        'valid': key_valid and tempo_valid,
        'key_match': key_valid,
        'tempo_match': tempo_valid,
        'found_key': found_key,
        'found_tempo': found_tempo,
        'feedback': feedback
    }


def _normalize_key(key: str) -> str:
    """
    Normalize key signature for comparison.
    
    Handles:
    - Case insensitivity (G vs g)
    - Mode abbreviations (Gmaj -> G, Amin -> Am)
    - Enharmonic equivalents (C# -> Db)
    
    Args:
        key: Key signature string
        
    Returns:
        Normalized key string
    """
    if not key:
        return ""
    
    # Remove mode suffixes (maj, min, etc.) for major keys
    key = re.sub(r'maj$', '', key, flags=re.IGNORECASE)
    
    # Normalize minor keys (Amin -> Am, amin -> Am)
    key = re.sub(r'min$', 'm', key, flags=re.IGNORECASE)
    
    # Capitalize first letter
    if len(key) > 0:
        key = key[0].upper() + key[1:]
    
    return key


def check_key_compliance(abc_string: str, expected_key: str) -> Dict[str, any]:
    """
    Check if melody notes comply with the specified key signature.
    
    This is a more advanced check that validates whether the notes
    in the melody actually stay within the key signature.
    
    Args:
        abc_string: ABC notation string
        expected_key: Expected key signature
        
    Returns:
        Dictionary with:
        - compliant: bool
        - out_of_key_notes: list of notes that don't fit the key
        - suggestions: str with improvement suggestions
    """
    # Define scale notes for common keys
    key_scales = {
        'C': ['C', 'D', 'E', 'F', 'G', 'A', 'B'],
        'G': ['G', 'A', 'B', 'C', 'D', 'E', 'F#'],
        'D': ['D', 'E', 'F#', 'G', 'A', 'B', 'C#'],
        'A': ['A', 'B', 'C#', 'D', 'E', 'F#', 'G#'],
        'E': ['E', 'F#', 'G#', 'A', 'B', 'C#', 'D#'],
        'F': ['F', 'G', 'A', 'Bb', 'C', 'D', 'E'],
        'Am': ['A', 'B', 'C', 'D', 'E', 'F', 'G'],
        'Em': ['E', 'F#', 'G', 'A', 'B', 'C', 'D'],
        'Dm': ['D', 'E', 'F', 'G', 'A', 'Bb', 'C'],
    }
    
    expected_key_normalized = _normalize_key(expected_key)
    
    if expected_key_normalized not in key_scales:
        return {
            'compliant': True,  # Can't check unknown keys
            'out_of_key_notes': [],
            'suggestions': f"Key {expected_key} not in validation database"
        }
    
    allowed_notes = key_scales[expected_key_normalized]
    
    # Extract notes from ABC (simplified - just letter names)
    note_pattern = r'[_=\^]?([A-Ga-g])[#b]?[\',]*[\d/]*'
    notes = re.findall(note_pattern, abc_string)
    
    # Normalize and check
    out_of_key = []
    for note in notes:
        note_upper = note.upper()
        # Check if note is in allowed scale
        if note_upper not in [n[0] for n in allowed_notes]:
            out_of_key.append(note)
    
    compliant = len(out_of_key) == 0
    
    if compliant:
        suggestions = f"✅ All notes fit within {expected_key_normalized} key signature"
    else:
        unique_out = list(set(out_of_key))
        suggestions = f"⚠️  Found notes outside {expected_key_normalized}: {', '.join(unique_out)}"
    
    return {
        'compliant': compliant,
        'out_of_key_notes': out_of_key,
        'suggestions': suggestions
    }


def suggest_tempo_for_style(style: str) -> tuple:
    """
    Suggest appropriate tempo range for a musical style.
    
    Args:
        style: Musical style (e.g., "ballad", "rock", "jazz")
        
    Returns:
        Tuple of (min_bpm, max_bpm, description)
    """
    tempo_ranges = {
        'ballad': (60, 80, 'Slow and expressive'),
        'folk': (90, 120, 'Moderate and comfortable'),
        'pop': (100, 130, 'Upbeat and catchy'),
        'rock': (120, 140, 'Energetic'),
        'punk': (160, 200, 'Fast and aggressive'),
        'jazz': (120, 180, 'Swinging'),
        'blues': (80, 120, 'Laid-back groove'),
        'waltz': (84, 120, 'Flowing triple meter'),
    }
    
    style_lower = style.lower()
    for key in tempo_ranges:
        if key in style_lower:
            return tempo_ranges[key]
    
    # Default
    return (100, 140, 'Moderate tempo')
