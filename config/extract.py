import json

target = ['/home/liurixin25/liurixin/gscc/ns-allinone-3.19/ns-3.19/config/flow_output_150-150', '/home/liurixin25/liurixin/gscc/ns-allinone-3.19/ns-3.19/config/flow_output_150-200']
file_name = ['w-dynamic-150-150.txt', 'w-dynamic-150-200.txt']
cnt = 0
for file_path in target:
    with open(file_path, 'r') as file:
        data = json.load(file)
        output_lines = []
        output_lines.append(str(len(data)))        
        for item in data:
            line = f"{item.get('src')} {item.get('dst')} 3 {item.get('fsize')} {item.get('start_time')}"
            output_lines.append(line)
        result = '\n'.join(output_lines)
        with open(file_name[cnt], 'w') as f:
            f.write(result)
        cnt += 1
