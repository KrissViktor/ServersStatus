"""Display PowerShell CLIXML as text, omitting its progress transport objects."""
import re
import xml.etree.ElementTree as ET

_NAMESPACE='http://schemas.microsoft.com/powershell/2004/04'
_BLOCK=re.compile(r'<Objs\b[^>]*\bxmlns=[\"\']'+re.escape(_NAMESPACE)+r'[\"\'][^>]*>.*?(?:</Objs>|\Z)',re.S)
_ESCAPE=re.compile(r'_x([0-9a-fA-F]{4})_')


def clean_output(text):
    def decode(value):return _ESCAPE.sub(lambda m:chr(int(m.group(1),16)),value)
    def replace(match):
        block=match.group(0)
        # Transport XML is never expected to contain a DTD/entity declaration.
        if '<!DOCTYPE' in block or '<!ENTITY' in block:return block
        try:root=ET.fromstring(block)
        except ET.ParseError:
            # An in-progress snapshot may stop inside a progress object.
            streams=re.findall(r'\bS=[\"\']([^\"\']+)[\"\']',block)
            return '' if streams and all(s.casefold()=='progress' for s in streams) else block
        lines=[]
        for element in root:
            if element.attrib.get('S','').casefold()=='progress':continue
            if element.tag=='{'+_NAMESPACE+'}S':lines.append(decode(element.text or ''))
            else:
                value=element.find('{'+_NAMESPACE+'}ToString')
                if value is not None:lines.append(decode(value.text or ''))
                else:lines.extend(decode(s.text or '') for s in element.iter('{'+_NAMESPACE+'}S'))
        return '\n'.join(lines)
    if _NAMESPACE not in text:return text
    cleaned=_BLOCK.sub(replace,text)
    return re.sub(r'(?m)^#< CLIXML\r?\n?', '',cleaned)
