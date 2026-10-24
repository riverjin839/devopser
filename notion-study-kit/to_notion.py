import re,sys
def esc_inline(s):
    # escape outside inline code spans
    parts=re.split(r'(`[^`]*`)',s)
    out=[]
    for p in parts:
        if p.startswith('`') and p.endswith('`') and len(p)>1:
            out.append(p); continue
        p=p.replace('\\','\\\\')
        for ch in ['~','$','[',']','<','>','{','}','^','|']:
            p=p.replace(ch,'\\'+ch)
        out.append(p)
    return ''.join(out)
def conv(text):
    lines=text.split('\n')
    # drop title line
    if lines[0].startswith('## '): lines=lines[1:]
    out=[];i=0;incode=False;lang=''
    while i<len(lines):
        l=lines[i]
        if l.startswith('```'):
            if not incode:
                incode=True;lang=l[3:].strip()
            else:
                incode=False
            out.append(l);i+=1;continue
        if incode:
            if lang=='mermaid': l=l.replace('<br/>','<br>')
            out.append(l);i+=1;continue
        if l.startswith('|') and i+1<len(lines) and re.match(r'^\|[-| ]+\|$',lines[i+1]):
            rows=[l]; i+=2
            while i<len(lines) and lines[i].startswith('|'):
                rows.append(lines[i]); i+=1
            out.append('<table header-row="true" fit-page-width="true">')
            for r in rows:
                cells=[c.strip() for c in r.strip().strip('|').split('|')]
                out.append('\t<tr>')
                for c in cells: out.append('\t\t<td>'+esc_inline(c)+'</td>')
                out.append('\t</tr>')
            out.append('</table>')
            continue
        if l.strip()=='---' or l.startswith('#'):
            if l.startswith('#'):
                m=re.match(r'^(#+ )(.*)$',l); l=m.group(1)+esc_inline(m.group(2))
            out.append(l);i+=1;continue
        m=re.match(r'^(\s*(?:> |- |\d+\. )?)(.*)$',l)
        out.append(m.group(1)+esc_inline(m.group(2)));i+=1
    return '\n'.join(out).strip()+'\n'
for f in sys.argv[1:]:
    open(f.replace('.md','.notion.md'),'w').write(conv(open(f).read()))
