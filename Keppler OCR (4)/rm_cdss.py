with open("Frontend OCR/src/app/App.tsx", "r") as f:
    lines = f.readlines()

to_delete = set()
to_delete.add(28-1)
to_delete.add(34-1)
for i in range(516-1, 522-1):
    to_delete.add(i)
to_delete.add(564-1)
for i in range(1916-1, 2227-1):
    to_delete.add(i)
to_delete.add(2722-1)

new_lines = [line for i, line in enumerate(lines) if i not in to_delete]

with open("Frontend OCR/src/app/App.tsx", "w") as f:
    f.writelines(new_lines)
