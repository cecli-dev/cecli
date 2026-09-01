#!/bin/bash

echo "Calculating Ideal Tokens For Tokenization"

# Write the Python script to a temporary file
cat << 'EOF' > /tmp/table_optimizer.py
import pprint
import tiktoken
import unicodedata
from transformers import AutoTokenizer

def find_anthropic_safe_tokens_with_fallback(target_count=1024):
    print("Loading tokenizers... (This will download vocab files to your cache)")
    
    enc_cl100k = tiktoken.get_encoding("cl100k_base")
    enc_o200k = tiktoken.get_encoding("o200k_base")
    
    tokenizers = {
        "qwen": AutoTokenizer.from_pretrained("Qwen/Qwen2.5-7B"),
        "mistral_nemo": AutoTokenizer.from_pretrained("mistralai/Mistral-Nemo-Base-2407"),
        "phi4": AutoTokenizer.from_pretrained("microsoft/Phi-4-mini-instruct", trust_remote_code=True),
        "glm4": AutoTokenizer.from_pretrained("THUDM/glm-4-9b-chat", trust_remote_code=True),
        "deepseek_v3": AutoTokenizer.from_pretrained("deepseek-ai/DeepSeek-V3", trust_remote_code=True),
    }

    print("Extracting candidates into Primary and Secondary (Fallback) pools...")
    primary_candidates = set()
    secondary_candidates = set()
    
    for token_id in range(enc_o200k.n_vocab):
        try:
            token_bytes = enc_o200k.decode_single_token_bytes(token_id)
            text = token_bytes.decode('utf-8')
            
            if len(text) == 1 and text.isprintable():
                char_code = ord(text)
                
                # 1. ASCII must be strictly alphanumeric
                if char_code <= 0x007F and not text.isalnum():
                    continue
                    
                # 2. PREVENT COMBINING CHARACTER COLLAPSE
                # Drops all attaching Marks (Mn, Mc, Me) and invisible format Controls (Cf, Cc)
                category = unicodedata.category(text)
                if category.startswith('M') or category.startswith('C'):
                    continue
                    
                # 3. DECOMPOSITION ROUTING
                if unicodedata.decomposition(text):
                    # Has hidden structural parts -> send to Fallback Pool
                    secondary_candidates.add(text)
                else:
                    # Pure, unbreakable character -> send to Primary Pool
                    primary_candidates.add(text)
                    
        except (KeyError, UnicodeDecodeError):
            pass

    # Sort to sequentially process alphabets from standard to complex
    primary_sorted = sorted(list(primary_candidates), key=ord)
    secondary_sorted = sorted(list(secondary_candidates), key=ord)
    
    print(f"Extracted {len(primary_sorted)} Primary and {len(secondary_sorted)} Secondary candidates.")
    
    shared_tokens = []
    
    # Helper function to process a specific pool
    def process_pool(candidate_list, pool_name):
        print(f"\n--- Scanning {pool_name} Pool ---")
        for text in candidate_list:
            if len(enc_cl100k.encode(text)) != 1:
                continue
                
            is_shared = True
            for enc in tokenizers.values():
                if len(enc.encode(text, add_special_tokens=False)) != 1:
                    is_shared = False
                    break
                    
            if is_shared:
                shared_tokens.append(text)
                if len(shared_tokens) % 64 == 0:
                    print(f"Secured {len(shared_tokens)} / {target_count} universal tokens...")
                
            if len(shared_tokens) == target_count:
                break

    # 1. Exhaust the Primary Pool first
    process_pool(primary_sorted, "PRIMARY (Strictly Safe)")
    
    # 2. If we fell short (e.g. 1009/1024), dip into the Secondary Pool
    if len(shared_tokens) < target_count:
        print(f"\nTarget not met ({len(shared_tokens)}/{target_count}). Dipping into SECONDARY fallback pool...")
        process_pool(secondary_sorted, "SECONDARY (Decomposed)")

    return shared_tokens

if __name__ == "__main__":
    try:
        optimal_tokens = find_anthropic_safe_tokens_with_fallback(1024)
        print("\n" + "="*50)
        print(f"FOUND {len(optimal_tokens)} UNIVERSAL TOKENS (SORTED BY UNICODE)")
        print("="*50)
        pprint.pprint(optimal_tokens, compact=True, width=100)
    except Exception as e:
        print(f"Error: {e}")
EOF

# Execute the python script with the bash arguments
python3 /tmp/table_optimizer.py

# Clean up
rm /tmp/table_optimizer.py