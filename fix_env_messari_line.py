"""Herstelt de MESSARI_API_KEY-regel in .env, die per ongeluk zijn
naam-prefix kwijtraakte door een fout sed-commando."""

env_path = "/root/hbar_bot/.env"

with open(env_path, "r") as f:
    lines = f.readlines()

fixed_lines = []
for line in lines:
    stripped = line.strip()
    # De "losse", zonder-prefix regel herkennen (geen "=" erin, en niet leeg/commentaar)
    if stripped and "=" not in stripped and not stripped.startswith("#"):
        fixed_lines.append(f"MESSARI_API_KEY={stripped}\n")
        print(f"Hersteld: MESSARI_API_KEY={stripped}")
    else:
        fixed_lines.append(line)

with open(env_path, "w") as f:
    f.writelines(fixed_lines)

print("\nKlaar. Nieuwe inhoud:")
with open(env_path, "r") as f:
    print(f.read())
