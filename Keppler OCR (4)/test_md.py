import re
import markdown

safe = """**Referred Doctor:** Dr. Smith
| S.No | Test |
|---|---|
| 1 | CBC |"""

safe = re.sub(r'([^\|\n][ \t]*)\n([ \t]*\|)', r'\1\n\n\2', safe)
print("FIXED MARKDOWN:")
print(safe)

html = markdown.markdown(safe, extensions=['tables', 'nl2br'])
print("\nHTML:")
print(html)
