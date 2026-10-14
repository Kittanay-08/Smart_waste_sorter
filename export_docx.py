import re
import os
from pathlib import Path
import docx
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT, WD_ALIGN_VERTICAL
from docx.oxml import OxmlElement, parse_xml
from docx.oxml.ns import nsdecls, qn

FONT_NAME = "TH Sarabun PSK"

def set_run_font(run, font_name=FONT_NAME, size_pt=16, bold=False, italic=False, color=None):
    run.font.name = font_name
    run.font.size = Pt(size_pt)
    run.bold = bold
    run.italic = italic
    if color:
        run.font.color.rgb = color
    rPr = run._r.get_or_add_rPr()
    rFonts = rPr.find(qn('w:rFonts'))
    if rFonts is None:
        rFonts = OxmlElement('w:rFonts')
        rPr.append(rFonts)
    rFonts.set(qn('w:ascii'), font_name)
    rFonts.set(qn('w:hAnsi'), font_name)
    rFonts.set(qn('w:cs'), font_name)

def set_cell_shading(cell, fill_hex):
    tcPr = cell._tc.get_or_add_tcPr()
    shd = parse_xml(f'<w:shd {nsdecls("w")} w:fill="{fill_hex}"/>')
    tcPr.append(shd)

def set_table_borders(table, color="CCCCCC", sz="4", val="single"):
    tblPr = table._tbl.tblPr
    borders = parse_xml(f'''
        <w:tblBorders {nsdecls("w")}>
            <w:top w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            <w:bottom w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            <w:left w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            <w:right w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            <w:insideH w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
            <w:insideV w:val="{val}" w:sz="{sz}" w:space="0" w:color="{color}"/>
        </w:tblBorders>
    ''')
    tblPr.append(borders)

def add_styled_paragraph(doc, text="", style='Normal', space_before=0, space_after=4, line_spacing=1.15, align=WD_ALIGN_PARAGRAPH.LEFT):
    p = doc.add_paragraph()
    p.alignment = align
    p.paragraph_format.space_before = Pt(space_before)
    p.paragraph_format.space_after = Pt(space_after)
    p.paragraph_format.line_spacing = line_spacing
    return p

def process_inline_formatting(p, text, default_size=16, default_color=None, default_bold=False, default_italic=False):
    # Regex split bold italic code math
    tokens = re.split(r'(\*\*.*?\*\*|\*.*?\*|`.*?`|\$.*?\$)', text)
    for token in tokens:
        if not token:
            continue
        if token.startswith('**') and token.endswith('**') and len(token) >= 4:
            clean = token[2:-2]
            run = p.add_run(clean)
            set_run_font(run, FONT_NAME, default_size, bold=True, italic=default_italic, color=default_color)
        elif token.startswith('*') and token.endswith('*') and len(token) >= 2:
            clean = token[1:-1]
            run = p.add_run(clean)
            set_run_font(run, FONT_NAME, default_size, bold=default_bold, italic=True, color=default_color)
        elif token.startswith('`') and token.endswith('`') and len(token) >= 2:
            clean = token[1:-1]
            run = p.add_run(clean)
            set_run_font(run, "Consolas", default_size - 1, bold=False, italic=False, color=RGBColor(40, 80, 160))
        elif token.startswith('$') and token.endswith('$') and len(token) >= 2:
            clean = token[1:-1]
            run = p.add_run(clean)
            set_run_font(run, FONT_NAME, default_size, bold=False, italic=True, color=default_color)
        else:
            run = p.add_run(token)
            set_run_font(run, FONT_NAME, default_size, bold=default_bold, italic=default_italic, color=default_color)

def main():
    base_dir = Path(__file__).parent
    md_path = base_dir / "PROJECT_REPORT_25_PAGES.md"
    docx_path = base_dir / "PROJECT_REPORT_25_PAGES.docx"

    with open(md_path, "r", encoding="utf-8") as f:
        lines = f.readlines()

    doc = docx.Document()

    # Set Margins (Standard Thai Academic: Top 1.25", Bottom 1", Left 1.25", Right 1")
    for section in doc.sections:
        section.top_margin = Inches(1.2)
        section.bottom_margin = Inches(1.0)
        section.left_margin = Inches(1.25)
        section.right_margin = Inches(1.0)
        section.page_width = Inches(8.27)  # A4
        section.page_height = Inches(11.69) # A4

    in_code_block = False
    code_block_lines = []
    in_table = False
    table_lines = []

    def flush_table():
        nonlocal table_lines, in_table
        if not table_lines:
            in_table = False
            return
        # Parse table lines
        parsed_rows = []
        for tline in table_lines:
            # Skip separator lines like |---|---|
            if re.match(r'^\s*\|?\s*[-:\s|]+\s*\|?\s*$', tline):
                continue
            cols = [c.strip() for c in tline.split('|')]
            if cols and cols[0] == '':
                cols = cols[1:]
            if cols and cols[-1] == '':
                cols = cols[:-1]
            if cols:
                parsed_rows.append(cols)
        
        if parsed_rows:
            col_count = max(len(r) for r in parsed_rows)
            # normalize row lengths
            for r in parsed_rows:
                while len(r) < col_count:
                    r.append("")
            
            t = doc.add_table(rows=len(parsed_rows), cols=col_count)
            t.alignment = WD_TABLE_ALIGNMENT.CENTER
            set_table_borders(t, color="B0B0B0")

            for r_idx, row_data in enumerate(parsed_rows):
                for c_idx, cell_data in enumerate(row_data):
                    cell = t.cell(r_idx, c_idx)
                    cell.vertical_alignment = WD_ALIGN_VERTICAL.CENTER
                    p = cell.paragraphs[0]
                    p.paragraph_format.space_before = Pt(3)
                    p.paragraph_format.space_after = Pt(3)
                    p.paragraph_format.line_spacing = 1.1
                    
                    if r_idx == 0:
                        set_cell_shading(cell, "2C3E50")
                        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        process_inline_formatting(p, cell_data, default_size=15, default_color=RGBColor(255, 255, 255), default_bold=True)
                    else:
                        if r_idx % 2 == 1:
                            set_cell_shading(cell, "F8F9FA")
                        else:
                            set_cell_shading(cell, "FFFFFF")
                        # alignment
                        if len(cell_data) < 15 and (cell_data.isdigit() or re.match(r'^[\d.\s%]+$', cell_data)):
                            p.alignment = WD_ALIGN_PARAGRAPH.CENTER
                        else:
                            p.alignment = WD_ALIGN_PARAGRAPH.LEFT
                        process_inline_formatting(p, cell_data, default_size=15, default_color=RGBColor(30, 30, 30))

            p_space = doc.add_paragraph()
            p_space.paragraph_format.space_before = Pt(0)
            p_space.paragraph_format.space_after = Pt(4)

        table_lines = []
        in_table = False

    def flush_code():
        nonlocal code_block_lines, in_code_block
        if not code_block_lines:
            in_code_block = False
            return
        code_text = "".join(code_block_lines)
        table = doc.add_table(rows=1, cols=1)
        table.alignment = WD_TABLE_ALIGNMENT.CENTER
        cell = table.cell(0, 0)
        set_cell_shading(cell, "F0F3F6")
        set_table_borders(table, color="D0D7DE")
        p = cell.paragraphs[0]
        p.paragraph_format.space_before = Pt(4)
        p.paragraph_format.space_after = Pt(4)
        p.paragraph_format.line_spacing = 1.15
        run = p.add_run(code_text.strip())
        set_run_font(run, "Consolas", size_pt=13, color=RGBColor(30, 30, 30))
        
        p_space = doc.add_paragraph()
        p_space.paragraph_format.space_after = Pt(4)
        code_block_lines = []
        in_code_block = False

    for line in lines:
        stripped = line.strip()

        # Code block handling
        if stripped.startswith("```"):
            if in_code_block:
                flush_code()
            else:
                if in_table:
                    flush_table()
                in_code_block = True
                code_block_lines = []
            continue

        if in_code_block:
            code_block_lines.append(line)
            continue

        # Table handling
        if "|" in stripped and not stripped.startswith("#"):
            if not in_table:
                in_table = True
                table_lines = []
            table_lines.append(stripped)
            continue
        elif in_table:
            flush_table()

        # Empty line
        if not stripped:
            continue

        # Page breaks before major chapters
        if stripped.startswith("# บทที่") or stripped.startswith("# บรรณานุกรม") or stripped.startswith("# ภาคผนวก"):
            doc.add_page_break()
            p = add_styled_paragraph(doc, space_before=12, space_after=8, align=WD_ALIGN_PARAGRAPH.CENTER)
            title_text = re.sub(r'^#+\s*', '', stripped)
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=20, bold=True, color=RGBColor(24, 43, 73))
            continue

        if stripped.startswith("## บทคัดย่อ") or stripped.startswith("## สารบัญ"):
            doc.add_page_break()
            p = add_styled_paragraph(doc, space_before=12, space_after=8, align=WD_ALIGN_PARAGRAPH.CENTER)
            title_text = re.sub(r'^#+\s*', '', stripped)
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=20, bold=True, color=RGBColor(24, 43, 73))
            continue

        # Document main Title (Cover header)
        if stripped.startswith("# "):
            p = add_styled_paragraph(doc, space_before=14, space_after=6, align=WD_ALIGN_PARAGRAPH.CENTER)
            title_text = stripped[2:].strip()
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=22, bold=True, color=RGBColor(20, 40, 80))
            continue

        if stripped.startswith("## "):
            p = add_styled_paragraph(doc, space_before=10, space_after=5, align=WD_ALIGN_PARAGRAPH.CENTER if "ข้อมูลโครงงาน" in stripped or "Abstract" in stripped else WD_ALIGN_PARAGRAPH.LEFT)
            title_text = stripped[3:].strip()
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=18, bold=True, color=RGBColor(35, 65, 110))
            continue

        if stripped.startswith("### "):
            p = add_styled_paragraph(doc, space_before=8, space_after=4, align=WD_ALIGN_PARAGRAPH.LEFT)
            title_text = stripped[4:].strip()
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=16, bold=True, color=RGBColor(40, 40, 40))
            continue

        if stripped.startswith("#### "):
            p = add_styled_paragraph(doc, space_before=6, space_after=3, align=WD_ALIGN_PARAGRAPH.LEFT)
            title_text = stripped[5:].strip()
            run = p.add_run(title_text)
            set_run_font(run, FONT_NAME, size_pt=16, bold=True, color=RGBColor(50, 50, 50))
            continue

        # Horizontal rule
        if stripped == "---":
            continue

        # Blockquote
        if stripped.startswith("> "):
            p = add_styled_paragraph(doc, space_before=4, space_after=4, align=WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.left_indent = Inches(0.4)
            process_inline_formatting(p, stripped[2:].strip(), default_size=15, default_italic=True, default_color=RGBColor(60, 60, 60))
            continue

        # Bullet list item
        if stripped.startswith("* ") or stripped.startswith("- "):
            p = add_styled_paragraph(doc, space_before=2, space_after=2, align=WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.left_indent = Inches(0.3)
            run_bullet = p.add_run("•  ")
            set_run_font(run_bullet, FONT_NAME, size_pt=15, bold=True, color=RGBColor(30, 80, 160))
            process_inline_formatting(p, stripped[2:].strip(), default_size=16)
            continue

        # Numbered list item
        num_match = re.match(r'^(\d+[\.\)]\s+)(.*)$', stripped)
        if num_match:
            p = add_styled_paragraph(doc, space_before=2, space_after=2, align=WD_ALIGN_PARAGRAPH.LEFT)
            p.paragraph_format.left_indent = Inches(0.3)
            run_num = p.add_run(num_match.group(1))
            set_run_font(run_num, FONT_NAME, size_pt=16, bold=True, color=RGBColor(30, 30, 30))
            process_inline_formatting(p, num_match.group(2), default_size=16)
            continue

        # Standard Paragraph with academic first-line indent
        p = add_styled_paragraph(doc, space_before=2, space_after=4, align=WD_ALIGN_PARAGRAPH.JUSTIFY if hasattr(WD_ALIGN_PARAGRAPH, 'JUSTIFY') else WD_ALIGN_PARAGRAPH.LEFT)
        p.paragraph_format.first_line_indent = Inches(0.4)
        process_inline_formatting(p, stripped, default_size=16)

    if in_table:
        flush_table()
    if in_code_block:
        flush_code()

    try:
        doc.save(str(docx_path))
        print(f"Successfully generated DOCX at: {docx_path}")
    except PermissionError:
        alt_path = base_dir / "PROJECT_REPORT_25_PAGES_NO_COLON.docx"
        doc.save(str(alt_path))
        print(f"Original file was locked by Word. Successfully saved to: {alt_path}")

if __name__ == "__main__":
    main()
