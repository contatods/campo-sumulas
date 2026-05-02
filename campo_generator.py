"""
campo_generator.py — CAMPO v7
Módulo de geração de súmulas HTML. Importado pelo servidor web.
"""

import os, re, base64
from jinja2 import Template


def font_b64(path):
    """Carrega fonte como base64 a partir de um caminho completo."""
    if os.path.exists(path):
        return base64.b64encode(open(path, "rb").read()).decode()
    return ""


def load_fonts(font_dir=None):
    """Localiza e carrega fontes Lato em base64.
    Tenta vários diretórios em ordem: argumento, ./fonts/, sistema."""
    search = []
    if font_dir:
        search.append(font_dir)
    # Pasta local 'fonts/' relativa ao módulo
    here = os.path.dirname(os.path.abspath(__file__))
    search.append(os.path.join(here, "fonts"))
    # Linux
    search.append("/usr/share/fonts/truetype/lato")
    # macOS
    search += [
        os.path.expanduser("~/Library/Fonts"),
        "/Library/Fonts",
        "/System/Library/Fonts",
    ]
    # Windows
    windir = os.environ.get("WINDIR", "C:\\Windows")
    search.append(os.path.join(windir, "Fonts"))

    for d in search:
        if not os.path.isdir(d):
            continue
        b = font_b64(os.path.join(d, "Lato-Black.ttf"))
        if b:
            print(f"  ✓ Fontes carregadas de: {d}")
            return {
                "black": b,
                "bold":  font_b64(os.path.join(d, "Lato-Bold.ttf")),
                "reg":   font_b64(os.path.join(d, "Lato-Regular.ttf")),
                "light": font_b64(os.path.join(d, "Lato-Light.ttf")),
            }
    print("  ⚠  Fontes Lato não encontradas — usando Arial como fallback")
    return {"black": "", "bold": "", "reg": "", "light": ""}


def img_b64(path):
    """Converte imagem local para data URL base64."""
    if path and os.path.exists(path):
        ext = os.path.splitext(path)[1].lower().lstrip(".")
        mime = {"png": "image/png", "jpg": "image/jpeg",
                "jpeg": "image/jpeg", "svg": "image/svg+xml"}.get(ext, "image/png")
        return f"data:{mime};base64,{base64.b64encode(open(path, 'rb').read()).decode()}"
    return ""


def sanitize(n):
    """Sanitiza nome de arquivo."""
    return re.sub(r"[^a-zA-Z0-9_\-]", "_", n)



CSS = """
/* ═══════════════════════════════════════════════════════
   CAMPO v7 — tokens
   ink    #0F0F0F  near-black text
   panel  #1A1818  dark background (header, workout zone, score box left)
   dk     #2B2B2B  section banners, sep rows, cum col
   mid    #5A5A5A  secondary text
   ghost  #9A9A9A  labels, refs
   rule   #D0CBC2  warm table rules
   paper  #F8F5F2  alternate row tint
   field  #F4F0E8  writing field background
   w      #FFFFFF  white
   a      #E05C10  orange — score box border + badge + cum col only
   ═══════════════════════════════════════════════════════ */
/* B&W print palette
   Contraste máximo: preto sólido / branco / cinzas bem separados.
   Sem dependência de cor — hierarquia só por valor de luminosidade.
   panel #181818  — painéis escuros (leitura header/workout zone)
   dk    #3A3A3A  — escuro secundário (col acumulado, sep rows)
   mid   #545454  — texto secundário
   ghost #787878  — labels (escuro o suficiente p/ impressão)
   rule  #A0A0A0  — divisores de tabela (visíveis em papel)
   paper #E4E4E4  — linhas alternadas (diferença clara do branco)
   field #F0F0F0  — fundo de campos de preenchimento
   w     #FFFFFF  — branco puro (áreas de escrita) */
:root{
  --ink:   #000000;
  --panel: #181818;
  --dk:    #3A3A3A;
  --mid:   #545454;
  --ghost: #787878;
  --rule:  #A0A0A0;
  --paper: #E4E4E4;
  --field: #F0F0F0;
  --w:     #FFFFFF;
  --a:     #000000;
}
*,*::before,*::after{box-sizing:border-box;margin:0;padding:0}
@page{size:A4;margin:8mm}
body{
  font-family:'Lato',Arial,sans-serif;
  color:var(--ink);background:var(--w);
  width:194mm;font-size:8pt;
  -webkit-print-color-adjust:exact;print-color-adjust:exact;
  position:relative;
  display:flex;flex-direction:column;min-height:281mm;
}
.page-footer{margin-top:auto;}
.ds-credit{
  text-align:center;font-size:5pt;color:#bbb;
  letter-spacing:.1em;margin-top:3mm;
  font-family:var(--font-body);text-transform:uppercase;
}

/* ── A4 MARKER ── */
.a4-marker{
  position:absolute;top:281mm;left:-2mm;right:-2mm;height:0;
  border-top:2px dashed rgba(200,0,0,.5);pointer-events:none;z-index:999;
}
.a4-marker::after{
  content:'A4';position:absolute;right:0;top:-10px;
  font-size:7px;font-weight:700;color:rgba(200,0,0,.55);
  letter-spacing:.06em;font-family:Arial,sans-serif;
}
@media print{.a4-marker{display:none!important}}

/* ══════════════════════════════════════════════════════
   HEADER — 10mm dark panel
   ══════════════════════════════════════════════════════ */
.hdr{
  height:10mm;background:var(--panel);
  display:flex;align-items:stretch;
  margin-bottom:0;
}
.hdr-logo-col{
  width:22mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  padding:0 2.5mm;
  border-right:1px solid rgba(255,255,255,.07);
}
.hdr-logo{
  max-height:7mm;max-width:18mm;
  width:auto;height:auto;
  object-fit:contain;object-position:center;
  display:block;
}
.hdr-body{
  flex:1;display:flex;flex-direction:column;
  justify-content:center;padding:0 3.5mm;
  border-right:1px solid rgba(255,255,255,.07);
}
.hdr-event{
  font-size:10pt;font-weight:900;color:var(--w);
  letter-spacing:.07em;text-transform:uppercase;line-height:1;
}
.hdr-sep{color:rgba(255,255,255,.5);font-weight:300;margin:0 2mm}
.hdr-cat{
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.70);
  letter-spacing:.1em;text-transform:uppercase;margin-top:1mm;
}
.hdr-date-col{
  display:flex;align-items:center;padding:0 3.5mm;flex-shrink:0;
}
.hdr-date{font-size:6pt;color:rgba(255,255,255,.55);letter-spacing:.05em;text-transform:uppercase}
.hdr-cat-credit{
  font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.38);
  letter-spacing:.08em;text-transform:uppercase;margin-top:1.2mm;
}
.hdr-evento-col{
  width:22mm;flex-shrink:0;
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  padding:0 2.5mm;
  border-left:1px solid rgba(255,255,255,.07);
  gap:1.5mm;
}
.hdr-evento-logo{
  max-height:7mm;max-width:18mm;
  width:auto;height:auto;
  object-fit:contain;object-position:center;
  display:block;
}
.hdr-evento-date{font-size:5pt;color:rgba(255,255,255,.45);letter-spacing:.05em;text-transform:uppercase;line-height:1}

/* ══════════════════════════════════════════════════════
   PRÉ-WORKOUT ZONE
   Filled by the arbiter BEFORE the workout starts.
   Three rows: athlete name / raia+nº+box / árbitro+bateria
   Orange left border = "fill this first"
   ══════════════════════════════════════════════════════ */
.prekit{
  border:2px solid var(--ink);
  border-left:4px solid var(--ink);
  margin-top:2mm;margin-bottom:0;overflow:hidden;
}
/* PRÉ-WORKOUT header strip */
.pk-header{
  height:5mm;background:var(--panel);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 3mm;
}
.pk-header-t{
  font-size:6pt;font-weight:700;color:var(--w);
  letter-spacing:.18em;text-transform:uppercase;
}
.pk-header-s{
  font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.60);
  letter-spacing:.06em;text-transform:uppercase;
}
.pk-athlete-row{
  height:9mm;background:var(--field);
  border-bottom:1.5px solid var(--rule);
  padding:1mm 3mm 0;display:flex;flex-direction:column;
}
.pk-sub-row{
  display:flex;height:8mm;background:var(--field);
  border-bottom:2.5px solid var(--ink);
}
.pk-ops-row{
  display:flex;height:8mm;background:var(--w);
}
.pk-cell{
  display:flex;flex-direction:column;padding:0.8mm 3mm 0;
}
.pk-cell+.pk-cell{border-left:1px solid var(--rule)}

/* Shared: field label + write line */
.fl{
  font-size:5pt;font-weight:700;color:var(--mid);
  text-transform:uppercase;letter-spacing:.12em;
  flex-shrink:0;line-height:1;
}
.fline{
  border-bottom:1px solid var(--rule);
  margin-top:auto;margin-bottom:1mm;width:100%;
}
.fline-filled{
  font-size:9pt;font-weight:700;color:var(--ink);
  letter-spacing:.03em;padding-bottom:0.5mm;
  border-bottom:1.5px solid var(--ink);
}

/* ══════════════════════════════════════════════════════
   WORKOUT ZONE — 16mm dark panel
   Badge (orange) = workout number.
   Time cap right rail = arbiter reference during workout.
   ══════════════════════════════════════════════════════ */
.wkt-zone{
  min-height:11mm;height:auto;background:var(--panel);
  display:flex;align-items:stretch;
  margin-bottom:1.5mm;
  border-top:1px solid rgba(255,255,255,.05);
}
.wkt-badge{
  width:14mm;flex-shrink:0;
  background:var(--w);
  display:flex;align-items:center;justify-content:center;
  font-size:16pt;font-weight:900;color:var(--ink);line-height:1;
}
.wkt-badge-dual{
  width:14mm;flex-shrink:0;
  background:var(--w);
  display:flex;flex-direction:column;align-items:center;justify-content:center;
  gap:0;line-height:1;
}
.wkt-badge-dual .bd-num{
  font-size:11pt;font-weight:900;color:var(--ink);line-height:1.1;
}
.wkt-badge-dual .bd-sep{
  font-size:7pt;font-weight:700;color:var(--ghost);letter-spacing:.05em;
}
.sbn-badge{
  width:6mm;height:6mm;background:var(--w);border-radius:50%;
  display:flex;align-items:center;justify-content:center;
  font-size:8pt;font-weight:900;color:var(--ink);flex-shrink:0;
  margin-right:2mm;
}
.wkt-body{
  flex:1;display:flex;flex-direction:column;
  justify-content:center;padding:0 3.5mm;min-width:0;
}
.wkt-name{
  font-size:18pt;font-weight:900;color:var(--w);
  letter-spacing:-.02em;line-height:.95;text-transform:uppercase;
  white-space:normal;overflow-wrap:break-word;
}
.wkt-type{
  display:block;font-size:4.5pt;font-weight:700;
  color:rgba(255,255,255,.65);letter-spacing:.2em;
  text-transform:uppercase;margin-top:1mm;
}
.wkt-tc-rail{
  width:21mm;flex-shrink:0;
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  border-left:1px solid rgba(255,255,255,.15);gap:0.8mm;
}
.wkt-tc-lbl{
  font-size:4.5pt;font-weight:700;
  color:rgba(255,255,255,.70);letter-spacing:.18em;text-transform:uppercase;
}
.wkt-tc-val{
  font-size:12pt;font-weight:900;
  color:rgba(255,255,255,.9);letter-spacing:-.02em;line-height:1;
}

/* ══════════════════════════════════════════════════════
   DESCRIPTION
   ══════════════════════════════════════════════════════ */
.desc{border-left:2px solid var(--rule);padding:1mm 3mm;margin-bottom:1mm}
.dl  {font-size:6.5pt;line-height:1.4;color:var(--mid)}
.dl-t{font-weight:700;color:var(--ink)}
.dl-tc{font-weight:700;font-style:italic}

/* ══════════════════════════════════════════════════════
   MOVEMENT TABLE
   Sequential number: 14pt bold ink — arbiter locates
   position at a glance from a distance.
   Cumulative column: dark bg + orange — scoreboard ref.
   ══════════════════════════════════════════════════════ */
.mov-wrap{border:2px solid var(--ink);overflow:hidden;margin-bottom:0}

.mov-hdr{display:flex;background:var(--panel);height:6mm;align-items:center}
.mh-lbl{width:14mm;flex-shrink:0;border-left:1px solid rgba(255,255,255,.06)}
.mh-mov{
  flex:1;font-size:6pt;font-weight:700;
  color:rgba(255,255,255,.80);padding-left:3mm;
  letter-spacing:.14em;text-transform:uppercase;
}
.mh-reps{
  width:21mm;flex-shrink:0;text-align:center;
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.85);
  letter-spacing:.09em;text-transform:uppercase;
  background:var(--dk);
  border-left:1px solid rgba(255,255,255,.12);
  display:flex;align-items:center;justify-content:center;
}
.mh-cum{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:5.5pt;font-weight:700;color:rgba(255,255,255,.50);
  letter-spacing:.12em;text-transform:uppercase;
}

.mov-row{
  display:flex;align-items:stretch;min-height:6.5mm;
  border-top:1px solid var(--rule);background:var(--w);
}
.mov-row:nth-child(even){background:var(--paper)}

.mr-lbl{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  letter-spacing:.04em;text-align:center;
  border-left:1px solid var(--rule);padding:1mm;line-height:1.25;
}
.mr-name{
  flex:1;display:flex;align-items:center;
  padding:1mm 2.5mm;font-size:8pt;font-weight:700;color:var(--ink);
  line-height:1.2;text-transform:uppercase;
  border-left:1px solid var(--rule);
  gap:1.5mm;
}
.mr-reps-inline{
  font-size:6.5pt;font-weight:400;color:var(--ghost);
  flex-shrink:0;
}
.mr-reps{
  width:21mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:var(--dk)!important;
  border-left:1px solid rgba(255,255,255,.12);
  font-size:13pt;font-weight:900;color:var(--w);
}
.mr-cum{
  width:14mm;flex-shrink:0;
  display:flex;align-items:center;justify-content:center;
  background:var(--field)!important;
  font-size:10pt;font-weight:700;color:var(--mid);
  letter-spacing:-.02em;line-height:1;
  border-left:1px solid var(--rule);
}

/* Chegada — última linha da tabela, distinta das demais */
.chegada-inline{
  background:var(--ink)!important;
  border-top:2px solid rgba(255,255,255,.15);
}
.chegada-inline .mr-name{
  color:var(--w);letter-spacing:.06em;
  border-left-color:rgba(255,255,255,.12);
}
.chegada-inline .mr-reps-inline{
  color:rgba(255,255,255,.70);
}
.chegada-inline .mr-reps{
  background:var(--panel)!important;
  border-left-color:rgba(255,255,255,.08);
  color:var(--w);
}
.chegada-inline .mr-cum{
  background:rgba(255,255,255,.06)!important;
  color:rgba(255,255,255,.65);
  border-left-color:rgba(255,255,255,.1);
}
.chegada-inline .mr-lbl{
  color:rgba(255,255,255,.65);
  border-left-color:rgba(255,255,255,.1);
}

.sep-row{
  display:flex;align-items:center;justify-content:center;
  height:5mm;background:var(--dk);
}
.sep-txt{
  font-size:6pt;font-weight:700;
  color:rgba(255,255,255,.85);letter-spacing:.22em;text-transform:uppercase;
}

/* ══════════════════════════════════════════════════════
   SCORE BOX — dominant post-workout element
   Orange top border announces: "fill this now".
   Left dark panel = label. Right field = large write area.
   ══════════════════════════════════════════════════════ */
/* ══════════════════════════════════════════════════════
   SCORE BOX — horizontal layout with 4 integrated zones:
   [RESULTADO label] [TEMPO field] [REPS field] [TIME CAP]
   ══════════════════════════════════════════════════════ */
.score-box{
  display:flex;
  border:2px solid var(--panel);
  overflow:hidden;
  margin-bottom:1.5mm;
  height:16mm;
}
/* Left dark label */
.sb-lbl-col{
  width:28mm;flex-shrink:0;background:var(--panel);
  display:flex;flex-direction:column;
  align-items:flex-start;justify-content:center;
  padding:0 3mm;
  border-right:1px solid rgba(255,255,255,.08);
}
.sb-lbl-tag{
  font-size:4.5pt;font-weight:700;color:rgba(255,255,255,.65);
  letter-spacing:.28em;text-transform:uppercase;
}
.sb-lbl-name{
  font-size:8.5pt;font-weight:900;color:rgba(255,255,255,.85);
  text-transform:uppercase;margin-top:1mm;letter-spacing:.02em;
}
/* Write fields — branco puro para máximo contraste de escrita manual */
.sb-field{
  display:flex;flex-direction:column;
  background:var(--w);
  padding:2mm 3mm 2.5mm;
  border-right:1px solid var(--rule);
  justify-content:space-between;
}
.sb-field-tempo{flex:2}
.sb-field-reps {flex:1}
.sb-field-lbl{
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  text-transform:uppercase;letter-spacing:.14em;flex-shrink:0;
}
.sb-field-line{
  border-bottom:2px solid var(--ink);
  flex:1;margin-top:2mm;
}
/* Right dark time cap */
.sb-tc-col{
  width:28mm;flex-shrink:0;background:var(--panel);
  display:flex;flex-direction:column;
  align-items:center;justify-content:center;
  gap:1.5mm;
  border-left:1px solid rgba(255,255,255,.08);
}
.sb-tc-box{
  width:9mm;height:9mm;
  background:var(--w);
  border:1.5px solid var(--mid);
}
.sb-tc-lbl{
  font-size:4.5pt;font-weight:700;color:rgba(255,255,255,.75);
  letter-spacing:.18em;text-transform:uppercase;
}

/* SCORE ANNOUNCE STRIP — substitui acento laranja em B&W */
.score-section{
  height:4.5mm;background:var(--panel);
  display:flex;align-items:center;justify-content:space-between;
  padding:0 3mm;margin-top:1.5mm;margin-bottom:0;
}
.sc-t{font-size:6pt;font-weight:700;color:var(--w);letter-spacing:.18em;text-transform:uppercase}
.sc-s{font-size:4.5pt;font-weight:400;color:rgba(255,255,255,.60);letter-spacing:.06em;text-transform:uppercase}
.sb-tc-sub{font-size:3.5pt;font-weight:700;color:rgba(255,255,255,.55);letter-spacing:.08em;text-transform:uppercase;text-align:center;margin-top:.5mm}

/* EXPRESS score box — same horizontal structure, two write fields */
.score-box-dual{
  display:flex;
  border:2px solid var(--panel);
  overflow:hidden;
  margin-bottom:1.5mm;
  height:16mm;
}
.sb-phase-tag{
  font-size:4pt;font-weight:700;color:rgba(255,255,255,.65);
  letter-spacing:.18em;text-transform:uppercase;
}
.sb-phase-type{
  font-size:7.5pt;font-weight:900;color:rgba(255,255,255,.78);
  text-transform:uppercase;margin-top:0.8mm;
}
.sb-ph-lbl{
  font-size:4.5pt;font-weight:700;color:var(--ghost);
  letter-spacing:.14em;text-transform:uppercase;flex-shrink:0;
}
.sb-ph-line{flex:1;border-bottom:2px solid var(--ink);margin-top:2mm}

/* ══════════════════════════════════════════════════════
   AMRAP SCORECARD (unchanged from v6)
   ══════════════════════════════════════════════════════ */
.amrap-wrap{border:2px solid var(--ink);overflow:hidden;margin-bottom:0}
.amrap-hdr{display:flex;align-items:center;background:var(--panel);height:6mm}
.amrap-subhdr{display:flex;align-items:stretch;background:var(--paper);min-height:4.5mm;height:auto;border-bottom:1px solid var(--rule)}
.amrap-row{
  display:flex;align-items:stretch;min-height:7mm;
  border-top:1px solid var(--rule);background:var(--w);
}
.amrap-row:nth-child(even){background:var(--paper)}
.rplus-row{opacity:.6}
.ar-round{flex-shrink:0;display:flex;align-items:center;justify-content:center}
.ar-mov{flex:1;display:flex;align-items:stretch;border-left:1px solid var(--rule)}
.ar-mov-cell{flex:1;display:flex;align-items:center;justify-content:center;border-right:1px solid var(--rule)}
.ar-write{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid var(--rule);background:var(--w);
  display:flex;align-items:flex-start;padding:1mm;
}
.ar-ref{font-size:6.5pt;font-weight:700;color:var(--rule)}
.ar-ref-lbl{font-size:5pt;color:var(--rule);display:block;line-height:1.2}
.ar-reps-cell{flex-shrink:0;display:flex;align-items:stretch;border-left:1px solid var(--rule)}
.ar-reps-inner{display:flex;align-items:center;justify-content:center;width:100%}
.ar-write-strong{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid var(--mid);background:var(--w);
  display:flex;align-items:flex-start;padding:1mm;
}
.ar-cum-cell{
  flex-shrink:0;display:flex;align-items:stretch;
  background:var(--dk)!important;border-left:none;
}
.ar-cum-inner{display:flex;align-items:center;justify-content:center;width:100%}
.ar-write-cum{
  width:calc(100% - 2.5mm);height:calc(100% - 2.5mm);margin:1.25mm;
  border:1px solid rgba(255,255,255,.12);
  background:rgba(255,255,255,.04);
  display:flex;align-items:flex-start;padding:1mm;
}
.ar-ref-sb{font-size:6.5pt;font-weight:700;color:rgba(255,255,255,.55)}
.ar-ref-sb-lbl{font-size:5pt;color:rgba(255,255,255,.45);display:block;line-height:1.2}
.ah-n{flex-shrink:0;display:flex;align-items:center;justify-content:center;font-size:10pt;font-weight:900;color:rgba(255,255,255,.12)}
.ah-title{flex:1;font-size:7pt;font-weight:700;color:rgba(255,255,255,.7);padding-left:3mm;letter-spacing:.12em;text-transform:uppercase;display:flex;align-items:center;border-left:1px solid rgba(255,255,255,.07)}
.ah-ref{font-size:7pt;font-weight:300;color:rgba(255,255,255,.60);display:flex;align-items:center;padding-right:3mm}
.ash{display:flex;align-items:center;justify-content:center;font-size:4.5pt;font-weight:700;color:var(--mid);letter-spacing:.05em;text-transform:uppercase;text-align:center;white-space:normal;line-height:1.25;padding:0.8mm 1mm}
.ash-cum{background:var(--dk)!important;border-left:none;color:rgba(255,255,255,.75)!important}

/* ══════════════════════════════════════════════════════
   EXPRESS SECTION BANNERS
   ══════════════════════════════════════════════════════ */
.section-banner{
  background:var(--dk);height:5.5mm;
  display:flex;align-items:center;padding:0 3mm;
  margin-bottom:1.5mm;justify-content:space-between;
}
.sbn-t{font-size:7pt;font-weight:900;color:var(--w);letter-spacing:.1em;text-transform:uppercase}
.sbn-s{font-size:5.5pt;font-weight:300;color:rgba(255,255,255,.70);letter-spacing:.04em}
.rest-bar{
  background:var(--paper);height:3.5mm;
  display:flex;align-items:center;justify-content:center;
  margin:1mm 0;
  border-top:1px solid var(--rule);border-bottom:1px solid var(--rule);
  font-size:6pt;font-weight:700;color:var(--ghost);
  letter-spacing:.12em;text-transform:uppercase;
}

/* ══════════════════════════════════════════════════════
   SIGNATURES
   ══════════════════════════════════════════════════════ */
.sign-zone{display:flex;gap:2mm;margin-top:3mm;margin-bottom:1mm}
.sign-cell{
  border:1.5px solid var(--ink);height:10mm;
  padding:1.5mm 3mm 0;display:flex;flex-direction:column;
}
.sign-wide  {flex:0 0 calc(60% - 1mm)}
.sign-narrow{flex:1}
.no-rasure{
  text-align:center;font-size:5.5pt;color:var(--mid);
  margin-bottom:1.5mm;letter-spacing:.07em;text-transform:uppercase;
}

/* ══════════════════════════════════════════════════════
   OBSERVATIONS
   ══════════════════════════════════════════════════════ */
.obs-box{
  border:1.5px solid var(--ink);
  padding:1.5mm 3mm;display:flex;flex-direction:column;
  min-height:24mm;
}
.obs-lbl{font-size:5pt;font-weight:700;color:var(--ghost);letter-spacing:.13em;text-transform:uppercase;margin-bottom:1mm}
.obs-lines{flex:1;display:flex;flex-direction:column;justify-content:space-evenly}
.obs-line{border-bottom:1px solid var(--rule);min-height:3.5mm}

@media print{
  body{margin:0}
  .a4-marker{display:none!important}
  .mov-wrap,.prekit,.score-box,.score-box-dual,.sign-zone,.obs-box,.amrap-wrap{page-break-inside:avoid}
}
"""


MOV_TABLE_MACRO = r"""
{% macro mov_table(movimentos, num) %}
{% set has_lbl = movimentos | selectattr('label','defined') | selectattr('label') | list | length > 0 %}
<div class="mov-wrap">
  <div class="mov-hdr">
    {% if has_lbl %}<div class="mh-lbl"></div>{% endif %}
    <div class="mh-mov">Movimentos</div>
    <div class="mh-reps">Reps</div>
    <div class="mh-cum">Acumulado</div>
  </div>
  {% set ns = namespace(cum=0) %}
  {% for mov in movimentos %}
    {% if mov.separador is defined and mov.separador %}
      <div class="sep-row"><span class="sep-txt">{{ mov.separador | upper }}</span></div>
    {% elif mov.chegada is defined and mov.chegada %}
      {% set ns.cum = ns.cum + 1 %}
      <div class="mov-row chegada-inline">
        {% if has_lbl %}<div class="mr-lbl">—</div>{% endif %}
        <div class="mr-name">
          <span class="mr-reps-inline">(1)</span>CHEGADA
        </div>
        <div class="mr-reps">1</div>
        <div class="mr-cum">{{ ns.cum }}</div>
      </div>
    {% else %}
      {% set ns.cum = ns.cum + (mov.reps | default(0)) %}
      <div class="mov-row">
        {% if has_lbl %}<div class="mr-lbl">{{ mov.label | default('') }}</div>{% endif %}
        <div class="mr-name">
          <span class="mr-reps-inline">({{ mov.reps }})</span>{{ mov.nome }}
        </div>
        <div class="mr-reps">{{ mov.reps }}</div>
        <div class="mr-cum">{{ ns.cum }}</div>
      </div>
    {% endif %}
  {% endfor %}
</div>
{% endmacro %}
"""

AMRAP_TABLE_MACRO = r"""
{% macro amrap_table(movimentos, num, n_rounds) %}
{% set data_movs = movimentos | rejectattr('separador','defined') | rejectattr('chegada','defined') | list %}
{% set reps_round = data_movs | map(attribute='reps') | list | sum %}
{% set rnd_w='14mm' %}{% set reps_w='21mm' %}{% set cum_w='14mm' %}
<div class="amrap-wrap">
  <div class="amrap-hdr">
    <div class="ah-n" style="width:{{rnd_w}}">{{ num }}</div>
    <div class="ah-title">Scorecard AMRAP</div>
    <div class="ah-ref">{{ reps_round }} reps / round</div>
  </div>
  <div class="amrap-subhdr">
    <div class="ash" style="width:{{rnd_w}}">Round</div>
    {% for m in data_movs %}
      {% set nc = m.nome.split('(')[0].strip() %}
      <div class="ash" style="flex:1;border-left:1px solid var(--rule)">{{ nc }}<br>({{ m.reps }})</div>
    {% endfor %}
    <div class="ash" style="width:{{reps_w}};border-left:1px solid var(--rule)">Reps/Rd</div>
    <div class="ash ash-cum" style="width:{{cum_w}}">Acumulado</div>
  </div>
  {% set ns = namespace(cum=0) %}
  {% for ri in range(n_rounds + 1) %}
    {% set ip = (ri == n_rounds) %}
    {% set rl = 'R+' if ip else (ri+1)|string %}
    <div class="amrap-row {% if ip %}rplus-row{% endif %}">
      <div class="ar-round" style="width:{{rnd_w}};border-right:1px solid var(--rule)">
        <span style="font-weight:900;font-size:{% if ip %}7{% else %}9{% endif %}pt;color:{% if ip %}var(--ghost){% else %}var(--mid){% endif %}">{{ rl }}</span>
      </div>
      <div class="ar-mov">
        {% for m in data_movs %}
        <div class="ar-mov-cell">
          <div class="ar-write">
            {% if not ip %}<span class="ar-ref"><span class="ar-ref-lbl">ref</span>{{ m.reps }}</span>{% endif %}
          </div>
        </div>
        {% endfor %}
      </div>
      <div class="ar-reps-cell" style="width:{{reps_w}}">
        <div class="ar-reps-inner">
          <div class="ar-write-strong">
            {% if not ip %}<span class="ar-ref"><span class="ar-ref-lbl">ref</span>{{ reps_round }}</span>{% endif %}
          </div>
        </div>
      </div>
      {% if not ip %}{% set ns.cum = ns.cum + reps_round %}{% endif %}
      <div class="ar-cum-cell" style="width:{{cum_w}}">
        <div class="ar-cum-inner">
          <div class="ar-write-cum">
            {% if not ip %}<span class="ar-ref-sb"><span class="ar-ref-sb-lbl">ref</span>{{ ns.cum }}</span>{% endif %}
          </div>
        </div>
      </div>
    </div>
  {% endfor %}
</div>
{% endmacro %}
"""

SCORE_BOX_MACRO = r"""
{% macro score_box(tipo) %}
{% if tipo == 'for_time' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">For Time</span>
    <span class="sb-lbl-name">Score</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Tempo</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">Reps</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% elif tipo == 'amrap' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">AMRAP</span>
    <span class="sb-lbl-name">Score</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">Rounds</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">Reps Extras</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% elif tipo == 'express' %}
<div class="score-section">
  <span class="sc-t">Resultado</span>
  <span class="sc-s">Preencher após o workout</span>
</div>
<div class="score-box-dual">
  <div class="sb-lbl-col">
    <span class="sb-lbl-tag">Express</span>
    <span class="sb-lbl-name">Score</span>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">F1 · Reps</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-tempo">
    <span class="sb-field-lbl">F2 · Tempo</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-field sb-field-reps">
    <span class="sb-field-lbl">F2 · Reps</span>
    <div class="sb-field-line"></div>
  </div>
  <div class="sb-tc-col">
    <div class="sb-tc-box"></div>
    <span class="sb-tc-lbl">Time Cap</span>
    <span class="sb-tc-sub">marcar se atingido</span>
  </div>
</div>
{% endif %}
{% endmacro %}
"""

TMPL_STR = r"""<!DOCTYPE html>
<html lang="pt-BR">
<head>
<meta charset="UTF-8">
<title>Súmula – {{ wkt.nome }}</title>
<style>
@font-face{font-family:'Lato';font-weight:900;src:url('data:font/truetype;base64,{{ fonts.black }}') format('truetype')}
@font-face{font-family:'Lato';font-weight:700;src:url('data:font/truetype;base64,{{ fonts.bold  }}') format('truetype')}
@font-face{font-family:'Lato';font-weight:400;src:url('data:font/truetype;base64,{{ fonts.reg   }}') format('truetype')}
@font-face{font-family:'Lato';font-weight:300;src:url('data:font/truetype;base64,{{ fonts.light }}') format('truetype')}
{{ css }}
</style>
</head>
<body>

<div class="a4-marker"></div>

{# ── HEADER ── #}
<div class="hdr">
  <div class="hdr-logo-col">
    {% if logo_src %}<img class="hdr-logo" src="{{ logo_src }}">{% endif %}
  </div>
  <div class="hdr-body">
    <div class="hdr-event">
      {{ ev.nome|upper }}{% if wkt.arena %}<span class="hdr-sep"> / </span>{{ wkt.arena|upper }}{% endif %}
    </div>
    {% if ev.categoria %}<div class="hdr-cat">{{ ev.categoria|upper }}</div>{% endif %}
  </div>
  <div class="hdr-evento-col">
    {% if logo_evento_src %}<img class="hdr-evento-logo" src="{{ logo_evento_src }}">{% endif %}
    {% if wkt.data or ev.data %}<div class="hdr-evento-date">{{ wkt.data or ev.data }}</div>{% endif %}
  </div>
</div>

{# ── PRÉ-WORKOUT ZONE ── #}
{% set tipo = wkt.tipo|default('for_time') %}
{% set modalidade = wkt.modalidade|default('individual') %}
{% set lbl_nome = {'individual':'Nome do Atleta','dupla':'Nome da Dupla','time':'Nome do Time'}[modalidade]|default('Nome do Atleta') %}
{% set lbl_sign = {'individual':'Assinatura do Atleta','dupla':'Assinatura do Capitão','time':'Assinatura do Capitão'}[modalidade]|default('Assinatura do Atleta') %}

<div class="prekit">
  <div class="pk-header">
    <span class="pk-header-t">Pré-Workout</span>
    <span class="pk-header-s">{% if not atleta %}Preencher antes do início{% endif %}</span>
  </div>
  <div class="pk-athlete-row">
    <div class="fl">{{ lbl_nome }}</div>
    {% if atleta and atleta.nome %}
    <div class="fline fline-filled">{{ atleta.nome }}</div>
    {% else %}
    <div class="fline"></div>
    {% endif %}
  </div>
  <div class="pk-sub-row">
    <div class="pk-cell" style="flex:0 0 21mm">
      <div class="fl">Raia</div>
      {% if atleta and atleta.raia %}<div class="fline fline-filled">{{ atleta.raia }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
    <div class="pk-cell" style="flex:0 0 22%">
      <div class="fl">Nº Competidor</div>
      {% if atleta and atleta.numero %}<div class="fline fline-filled">{{ atleta.numero }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
    <div class="pk-cell" style="flex:1">
      <div class="fl">Box / Afiliação</div>
      {% if atleta and atleta.box %}<div class="fline fline-filled">{{ atleta.box }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
  </div>
  <div class="pk-ops-row">
    <div class="pk-cell" style="flex:0 0 58%">
      <div class="fl">Árbitro / Juiz</div><div class="fline"></div>
    </div>
    <div class="pk-cell" style="flex:1">
      <div class="fl">Bateria / Heat</div>
      {% if atleta and atleta.bateria %}<div class="fline fline-filled">{{ atleta.bateria }}</div>{% else %}<div class="fline"></div>{% endif %}
    </div>
  </div>
</div>

{# ── WORKOUT ZONE ── #}
{% set tipo_labels = {'for_time':'For Time','amrap':'AMRAP','express':'Express — AMRAP + For Time','for_load':'For Load'} %}
<div class="wkt-zone">
  {% if tipo == 'express' and wkt.numero_f2 is defined %}
  <div class="wkt-badge-dual">
    <span class="bd-num">{{ wkt.numero }}</span>
    <span class="bd-sep">·</span>
    <span class="bd-num">{{ wkt.numero_f2 }}</span>
  </div>
  {% else %}
  <div class="wkt-badge">{{ wkt.numero }}</div>
  {% endif %}
  <div class="wkt-body">
    <div class="wkt-name">{{ wkt.nome }}</div>
    <span class="wkt-type">{{ tipo_labels[tipo] | default(tipo) }}</span>
  </div>
  {% if wkt.time_cap %}
  <div class="wkt-tc-rail">
    <span class="wkt-tc-lbl">Time Cap</span>
    <span class="wkt-tc-val">{{ wkt.time_cap }}</span>
  </div>
  {% endif %}
</div>

{# ── WORKOUT CONTENT ── #}
{% if tipo == 'express' %}
  {% set f1 = wkt.formula1 %}
  <div class="section-banner">
    <div style="display:flex;align-items:center">
      <div class="sbn-badge">{{ wkt.numero }}</div>
      <span class="sbn-t">Fórmula 1 — AMRAP</span>
    </div>
    <span class="sbn-s">{{ f1.janela }}</span>
  </div>
  {% if f1.descricao %}<div class="desc">{% for l in f1.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ amrap_table(f1.movimentos, wkt.numero, f1.n_rounds|default(3)) }}
  <div class="rest-bar">Descanso de 1 Minuto &nbsp;·&nbsp; Reset Barbell / Equipment</div>
  {% set f2 = wkt.formula2 %}
  <div class="section-banner">
    <div style="display:flex;align-items:center">
      <div class="sbn-badge">{{ wkt.numero_f2 if wkt.numero_f2 is defined else wkt.numero }}</div>
      <span class="sbn-t">Fórmula 2 — For Time</span>
    </div>
    <span class="sbn-s">{{ f2.janela }}</span>
  </div>
  {% if f2.descricao %}<div class="desc">{% for l in f2.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ mov_table(f2.movimentos, wkt.numero) }}

{% elif tipo == 'amrap' %}
  {% if wkt.descricao %}<div class="desc">{% for l in wkt.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ amrap_table(wkt.movimentos, wkt.numero, wkt.n_rounds|default(3)) }}

{% else %}
  {% if wkt.descricao %}<div class="desc">{% for l in wkt.descricao %}<div class="dl {% if loop.first %}dl-t{% elif 'time cap' in l.lower() %}dl-tc{% endif %}">{{ l }}</div>{% endfor %}</div>{% endif %}
  {{ mov_table(wkt.movimentos, wkt.numero) }}
{% endif %}

{# ── SCORE BOX ── #}
{{ score_box(tipo) }}

{# ── ASSINATURAS — coladas logo abaixo do score box ── #}
<div class="sign-zone">
  <div class="sign-cell sign-wide"><div class="fl">{{ lbl_sign }}</div><div class="fline"></div></div>
  <div class="sign-cell sign-narrow"><div class="fl">Assinatura do Árbitro / Juiz</div><div class="fline"></div></div>
</div>
<div class="no-rasure">Não rasure a súmula — Qualquer correção deve ser registrada no campo de observações</div>

{# ── FOOTER — observações sempre no rodapé da página ── #}
<div class="page-footer">
  <div class="obs-box">
    <div class="obs-lbl">Observações</div>
    <div class="obs-lines">
      <div class="obs-line"></div><div class="obs-line"></div>
      <div class="obs-line"></div><div class="obs-line"></div>
      <div class="obs-line"></div>
    </div>
  </div>
  <div class="ds-credit">Gerada pelo sistema Digital Score · Todos os direitos reservados à Digital Score · Reprodução proibida sem autorização</div>
</div>

</body>
</html>
"""


def render_workout(ev, wkt, fonts, logo_src, logo_evento="", atleta=None):
    """Renderiza uma súmula HTML completa para um workout.
    Se logo_src nao for fornecida, usa a logo padrao Digital Score embutida.
    """
    logo_final   = logo_src  # padrão definido em sumula_app.py
    logo_evt_src = logo_evento if logo_evento else ""
    tmpl = Template(MOV_TABLE_MACRO + AMRAP_TABLE_MACRO + SCORE_BOX_MACRO + TMPL_STR)
    return tmpl.render(ev=ev, wkt=wkt, fonts=fonts, css=CSS,
                       logo_src=logo_final, logo_evento_src=logo_evt_src,
                       atleta=atleta)
