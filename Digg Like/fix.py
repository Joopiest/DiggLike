with open('d:/JoopFirebase/Digg Like/Digg.py', 'r', encoding='utf-8') as f:
    content = f.read()

start_idx = content.find('html_code = f"""')
end_idx = content.find('"""', start_idx + 16) + 3

html_block = content[start_idx:end_idx]

html_block = html_block.replace('html_code = f"""', 'html_code = """')
html_block = html_block.replace('{js_data}', '__RAW_DATA__')
html_block = html_block.replace('{{', '{').replace('}}', '}')

new_content = content[:start_idx] + html_block + content[end_idx:]

insert_idx = new_content.find('components.html(html_code, height=600)')
new_content = new_content[:insert_idx] + 'html_code = html_code.replace("__RAW_DATA__", js_data)\n        ' + new_content[insert_idx:]

with open('d:/JoopFirebase/Digg Like/Digg.py', 'w', encoding='utf-8') as f:
    f.write(new_content)

print('Fixed successfully!')
