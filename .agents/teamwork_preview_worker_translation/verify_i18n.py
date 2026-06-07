import json
import os

locales = ['en', 'tr', 'de', 'fr', 'es', 'it', 'ja', 'zh', 'ko', 'ar', 'pt', 'ru']
i18n_dir = "/Users/nazmi/showMe_temp/ui/src/i18n"

# 1. Read en.json as source of truth
en_path = os.path.join(i18n_dir, "en.json")
with open(en_path, "r", encoding="utf-8") as f:
    en_data = json.load(f)
    en_keys = set(en_data.keys())

print(f"en.json loaded. Keys count: {len(en_keys)}")
assert len(en_keys) == 137, f"Expected 137 keys, but got {len(en_keys)}"

# 2. Check each locale file
all_good = True
for locale in locales:
    locale_file = f"{locale}.json"
    file_path = os.path.join(i18n_dir, locale_file)
    
    if not os.path.exists(file_path):
        print(f"Error: {locale_file} does not exist!")
        all_good = False
        continue
        
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            keys = set(data.keys())
            
            # Check length
            if len(keys) != 137:
                print(f"Error: {locale_file} has {len(keys)} keys, expected 137.")
                all_good = False
            
            # Check key parity
            missing = en_keys - keys
            extra = keys - en_keys
            
            if missing:
                print(f"Error: {locale_file} is missing keys: {missing}")
                all_good = False
            if extra:
                print(f"Error: {locale_file} has extra keys: {extra}")
                all_good = False
                
            # Verify {var} interpolation placeholders match
            for k in en_keys:
                if k in data:
                    en_val = en_data[k]
                    loc_val = data[k]
                    
                    # Extract variables like {var}
                    import re
                    en_vars = set(re.findall(r"\{(\w+)\}", en_val))
                    loc_vars = set(re.findall(r"\{(\w+)\}", loc_val))
                    
                    if en_vars != loc_vars:
                        print(f"Warning: Placeholder mismatch in key '{k}' for {locale_file}. en: {en_vars}, {locale}: {loc_vars}")
                        all_good = False
                        
    except Exception as e:
        print(f"Error: Failed to parse {locale_file}: {e}")
        all_good = False

if all_good:
    print("Verification PASSED: All 12 files have exact parity and valid JSON.")
else:
    print("Verification FAILED.")
