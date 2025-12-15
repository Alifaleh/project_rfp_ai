import zipfile
import io
import re

class SimpleDocxGenerator:
    """
    A lightweight, zero-dependency DOCX generator for Odoo.
    Uses 'altChunk' to embed HTML directly, allowing Word to render complex formatting.
    """
    
    def __init__(self):
        self.buffer = io.BytesIO()
        self.document_xml_body = ""
        self.rels = []
        self.html_parts = [] # List of tuples (id, html_content)
        self.media_parts = [] # List of tuples (id, image_bytes, filename)
        self.counter = 0
        
        # Initial Relationship for styles is optional but good practice
        # We will add relationships dynamicall for altChunks
        
    def add_heading(self, text, level=1):
        """
        Adds a native Word heading.
        """
        xml = "<w:p>"
        xml += f'<w:pPr><w:pStyle w:val="Heading{level}"/></w:pPr>'
        xml += f'<w:r><w:t>{self._escape_xml(text)}</w:t></w:r>'
        xml += "</w:p>"
        self.document_xml_body += xml

    def add_text(self, text):
        """
        Adds a native Word paragraph.
        """
        if not text: return
        for line in text.split('\n'):
            if line.strip():
                xml = "<w:p>"
                xml += f'<w:r><w:t>{self._escape_xml(text)}</w:t></w:r>'
                xml += "</w:p>"
                self.document_xml_body += xml

    def add_caption(self, text):
        """
        Adds a centered, gray caption.
        """
        if not text: return
        xml = "<w:p>"
        # Center alignment
        xml += '<w:pPr><w:jc w:val="center"/></w:pPr>'
        # Gray color (e.g., 767676)
        xml += f'<w:r><w:rPr><w:color w:val="767676"/></w:rPr><w:t>{self._escape_xml(text)}</w:t></w:r>'
        xml += "</w:p>"
        self.document_xml_body += xml

    def add_spacer(self):
        """
        Adds an empty paragraph for spacing.
        """
        self.document_xml_body += "<w:p/>"

    def add_html_chunk(self, html_content):
        """
        Embeds HTML content using w:altChunk.
        Word will render this HTML including tables, lists, formatting, etc.
        """
        if not html_content: return
        
        # 1. Create a unique ID for this relationship
        self.counter += 1
        r_id = f"rIdHtml{self.counter}"
        
        # 2. Store the HTML part
        self.html_parts.append((r_id, html_content))
        
        # 3. Add the altChunk reference in the document body
        self.document_xml_body += f'<w:altChunk r:id="{r_id}"/>'
        
    def add_image(self, image_bytes, width=400, height=300):
        """
        Embeds an image into the document, centered.
        width/height: approximate sizes in points (very rough) or pixels. 
        Word Uses EMUs (English Metric Units). 1 pixel = 9525 EMUs. 
        Default 400x300 px.
        """
        if not image_bytes: return

        self.counter += 1
        r_id = f"rIdImg{self.counter}"
        filename = f"image{self.counter}.png" # Assume PNG for now or detect?
        
        self.media_parts.append((r_id, image_bytes, filename))
        
        # Convert to EMU
        cx = int(width * 9525) 
        cy = int(height * 9525)

        # Drawing XML (Inline)
        xml = '<w:p><w:pPr><w:jc w:val="center"/></w:pPr><w:r><w:drawing>'
        xml += f'<wp:inline distT="0" distB="0" distL="0" distR="0"><wp:extent cx="{cx}" cy="{cy}"/><wp:effectExtent l="0" t="0" r="0" b="0"/><wp:docPr id="{self.counter}" name="Picture {self.counter}"/><wp:cNvGraphicFramePr><a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/></wp:cNvGraphicFramePr><a:graphic xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main"><a:graphicData uri="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:pic xmlns:pic="http://schemas.openxmlformats.org/drawingml/2006/picture"><pic:nvPicPr><pic:cNvPr id="{self.counter}" name="{filename}"/><pic:cNvPicPr/></pic:nvPicPr><pic:blipFill><a:blip r:embed="{r_id}"/><a:stretch><a:fillRect/></a:stretch></pic:blipFill><pic:spPr><a:xfrm><a:off x="0" y="0"/><a:ext cx="{cx}" cy="{cy}"/></a:xfrm><a:prstGeom prst="rect"><a:avLst/></a:prstGeom></pic:spPr></pic:pic></a:graphicData></a:graphic></wp:inline>'
        xml += '</w:drawing></w:r></w:p>'
        
        self.document_xml_body += xml

    def _escape_xml(self, text):
        return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

    def generate(self):
        with zipfile.ZipFile(self.buffer, 'a', zipfile.ZIP_DEFLATED) as zf:
            # 1. [Content_Types].xml
            zf.writestr('[Content_Types].xml', self._get_content_types_xml())
            # 2. _rels/.rels
            zf.writestr('_rels/.rels', self._get_global_rels_xml())
            # 3. word/document.xml
            zf.writestr('word/document.xml', self._get_document_xml())
            # 4. word/_rels/document.xml.rels
            zf.writestr('word/_rels/document.xml.rels', self._get_document_rels_xml())
            # 5. word/styles.xml
            zf.writestr('word/styles.xml', self._get_styles_xml())
            
            # 6. Write HTML Parts
            for r_id, content in self.html_parts:
                # Wrap HTML in basic structure
                full_html = f"<html><head><meta charset='utf-8'/></head><body>{content}</body></html>"
                # Add BOM for Word compatibility
                zf.writestr(f"word/html/{r_id}.html", ('\ufeff' + full_html).encode('utf-8'))
                
            # 7. Write Media Parts
            for r_id, img_data, filename in self.media_parts:
                zf.writestr(f"word/media/{filename}", img_data)

        self.buffer.seek(0)
        return self.buffer.getvalue()

    # --- XML Templates ---
    
    def _get_content_types_xml(self):
        # We must override html extension to be text/html or application/xhtml+xml
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Default Extension="html" ContentType="application/xhtml+xml"/>
<Default Extension="png" ContentType="image/png"/>
<Default Extension="jpeg" ContentType="image/jpeg"/>
<Default Extension="jpg" ContentType="image/jpeg"/>
<Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
<Override PartName="/word/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.styles+xml"/>
</Types>"""

    def _get_global_rels_xml(self):
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""

    def _get_document_rels_xml(self):
        xml = '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
        xml += '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">\n'
        xml += '<Relationship Id="rIdStyles" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>\n'
        
        # Add Relationships for HTML chunks
        for r_id, _ in self.html_parts:
            xml += f'<Relationship Id="{r_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/aFChunk" Target="html/{r_id}.html"/>\n'
            
        # Add Relationships for Media
        for r_id, _, filename in self.media_parts:
            xml += f'<Relationship Id="{r_id}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/image" Target="media/{filename}"/>\n'

        xml += '</Relationships>'
        return xml

    def _get_document_xml(self):
        return f"""<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships" xmlns:wp="http://schemas.openxmlformats.org/drawingml/2006/wordprocessingDrawing">
<w:body>
{self.document_xml_body}
</w:body>
</w:document>"""

    def _get_styles_xml(self):
        # Keep basic styles for native headers
        return """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<w:styles xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">
<w:docDefaults>
<w:rPrDefault><w:rPr><w:rFonts w:asciiTheme="minorHAnsi" w:hAnsiTheme="minorHAnsi" w:eastAsiaTheme="minorHAnsi"/><w:sz w:val="24"/><w:szCs w:val="24"/><w:lang w:val="en-US" w:eastAsia="en-US" w:bidi="ar-SA"/></w:rPr></w:rPrDefault>
<w:pPrDefault><w:pPr><w:spacing w:after="0" w:line="240" w:lineRule="auto"/></w:pPr></w:pPrDefault>
</w:docDefaults>
<w:style w:type="paragraph" w:styleId="Normal" w:default="1"><w:name w:val="Normal"/><w:qFormat/></w:style>
<w:style w:type="paragraph" w:styleId="Heading1"><w:name w:val="heading 1"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:link w:val="Heading1Char"/><w:uiPriority w:val="9"/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="480" w:after="0"/><w:outlineLvl w:val="0"/></w:pPr><w:rPr><w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi" w:eastAsiaTheme="majorHAnsi"/><w:b/><w:bCs/><w:color w:val="2F5496" w:themeColor="accent1" w:themeShade="BF"/><w:sz w:val="34"/><w:szCs w:val="34"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading2"><w:name w:val="heading 2"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:link w:val="Heading2Char"/><w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="260" w:after="260"/><w:outlineLvl w:val="1"/></w:pPr><w:rPr><w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi" w:eastAsiaTheme="majorHAnsi"/><w:b/><w:bCs/><w:color w:val="2F5496" w:themeColor="accent1" w:themeShade="BF"/><w:sz w:val="30"/><w:szCs w:val="30"/></w:rPr></w:style>
<w:style w:type="paragraph" w:styleId="Heading3"><w:name w:val="heading 3"/><w:basedOn w:val="Normal"/><w:next w:val="Normal"/><w:link w:val="Heading3Char"/><w:uiPriority w:val="9"/><w:unhideWhenUsed/><w:qFormat/><w:pPr><w:keepNext/><w:keepLines/><w:spacing w:before="240" w:after="240"/><w:outlineLvl w:val="2"/></w:pPr><w:rPr><w:rFonts w:asciiTheme="majorHAnsi" w:hAnsiTheme="majorHAnsi" w:eastAsiaTheme="majorHAnsi"/><w:b/><w:bCs/><w:color w:val="2F5496" w:themeColor="accent1" w:themeShade="BF"/><w:sz w:val="26"/><w:szCs w:val="26"/></w:rPr></w:style>
</w:styles>"""
