import xml.etree.ElementTree as ET
import base64
import sys
import os

def normalize_locale(loc):
    if not loc:
        return "en"
    if loc in ("en_US", "en-US"):
        return "en"
    if loc in ("id_ID", "id-ID"):
        return "id"
    return loc

def convert_ojs2_to_ojs34(input_path, output_path):
    print(f"[INFO] Membaca file OJS 2: {input_path}")
    
    if not os.path.exists(input_path):
        print(f"[ERROR] File tidak ditemukan: {input_path}")
        return False
        
    tree = ET.parse(input_path)
    root = tree.getroot()

    # OJS 2 root bisa berupa <issues> atau langsung <issue>
    if root.tag == "issues":
        ojs2_issue = root.find("issue")
    elif root.tag == "issue":
        ojs2_issue = root
    else:
        print(f"[ERROR] Tag root tidak dikenali: {root.tag}")
        return False

    if ojs2_issue is None:
        print("[ERROR] Elemen <issue> tidak ditemukan di dalam XML.")
        return False

    # 1. Inisialisasi Root <issue> untuk OJS 3.4
    ns_map = {
        "xmlns": "http://pkp.sfu.ca",
        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
        "xsi:schemaLocation": "http://pkp.sfu.ca native.xsd",
        "published": "1",
        "current": "0"
    }
    ojs3_issue = ET.Element("issue", ns_map)

    # DOI Issue
    issue_doi = ojs2_issue.find("./id[@type='doi']")
    if issue_doi is not None and issue_doi.text:
        doi_elem = ET.SubElement(ojs3_issue, "id", {"type": "doi"})
        doi_elem.text = issue_doi.text.strip()

    # Issue Identification (Volume, Number, Year, Title)
    issue_ident = ET.SubElement(ojs3_issue, "issue_identification")
    vol = ojs2_issue.find("volume")
    num = ojs2_issue.find("number")
    year = ojs2_issue.find("year")
    title = ojs2_issue.find("title")

    if vol is not None and vol.text:
        ET.SubElement(issue_ident, "volume").text = vol.text.strip()
    if num is not None and num.text:
        ET.SubElement(issue_ident, "number").text = num.text.strip()
    if year is not None and year.text:
        ET.SubElement(issue_ident, "year").text = year.text.strip()
    if title is not None and title.text:
        loc = normalize_locale(title.attrib.get("locale", "en"))
        t_elem = ET.SubElement(issue_ident, "title", {"locale": loc})
        t_elem.text = title.text.strip()

    # Date Published Issue
    date_pub = ojs2_issue.find("date_published")
    if date_pub is not None and date_pub.text:
        ET.SubElement(ojs3_issue, "date_published").text = date_pub.text.strip()

    # Sections (Kategori / Bagian Jurnal)
    sections_elem = ET.SubElement(ojs3_issue, "sections")
    
    # Kumpulkan semua section unik dari OJS 2
    sections_map = {}
    sec_seq_counter = 1
    for sec in ojs2_issue.findall("section"):
        sec_abbrev = sec.find("abbrev")
        sec_title = sec.find("title")
        
        abbrev_text = sec_abbrev.text.strip() if sec_abbrev is not None and sec_abbrev.text else "ART"
        title_text = sec_title.text.strip() if sec_title is not None and sec_title.text else "Articles"
        loc = normalize_locale(sec_title.attrib.get("locale", "en")) if sec_title is not None else "en"
        
        if abbrev_text not in sections_map:
            sections_map[abbrev_text] = {"title": title_text, "locale": loc}
            # Menambahkan atribut seq="1" agar tidak error setSequence di PHP 8.3
            # Atribut numerik wajib diisi angka agar tidak error TypeError di PHP 8.3
            sec_elem = ET.SubElement(sections_elem, "section", {
                "ref": abbrev_text,
                "seq": str(sec_seq_counter),
                "editor_restricted": "0",
                "meta_indexed": "1",
                "meta_reviewed": "1",
                "abstracts_not_required": "0",
                "hide_title": "0",
                "hide_author": "0",
                "abstract_word_count": "0"
            })
            sec_seq_counter += 1
            ET.SubElement(sec_elem, "abbrev", {"locale": loc}).text = abbrev_text
            ET.SubElement(sec_elem, "title", {"locale": loc}).text = title_text

    articles_elem = ET.SubElement(ojs3_issue, "articles")

    # 2. Proses Seluruh Artikel
    article_seq = 1
    file_id_counter = 1
    author_id_counter = 1

    for ojs2_sec in ojs2_issue.findall("section"):
        sec_abbrev_elem = ojs2_sec.find("abbrev")
        sec_abbrev = sec_abbrev_elem.text.strip() if sec_abbrev_elem is not None and sec_abbrev_elem.text else "ART"

        for ojs2_art in ojs2_sec.findall("article"):
            art_locale = normalize_locale(ojs2_art.attrib.get("locale", "en"))
            art_lang = ojs2_art.attrib.get("language", "en")
            art_date_pub = ojs2_art.find("date_published")
            pub_date_str = art_date_pub.text.strip() if art_date_pub is not None and art_date_pub.text else "2025-12-31"

            ojs3_art = ET.SubElement(articles_elem, "article", {
                "locale": art_locale,
                "stage": "production",
                "status": "3",  # 3 = STATUS_PUBLISHED
                "current_publication_id": str(article_seq),
                "date_submitted": pub_date_str
            })

            # Kumpulkan file galley PDF dari naskah
            galleys_to_create = []
            for ojs2_galley in ojs2_art.findall("galley"):
                embed_elem = ojs2_galley.find(".//embed")
                galley_label_elem = ojs2_galley.find("label")
                galley_doi_elem = ojs2_galley.find("./id[@type='doi']")
                
                label_text = galley_label_elem.text.strip() if galley_label_elem is not None and galley_label_elem.text else "PDF"
                
                if embed_elem is not None and embed_elem.text:
                    fn = embed_elem.attrib.get("filename", f"article_{article_seq}.pdf")
                    mime = embed_elem.attrib.get("mime_type", "application/pdf")
                    base64_data = embed_elem.text.strip()
                    try:
                        file_size = len(base64.b64decode(base64_data))
                    except Exception:
                        file_size = 0
                    ext = fn.rsplit(".", 1)[-1].lower() if "." in fn else "pdf"

                    current_file_id = file_id_counter
                    file_id_counter += 1

                    # Buat <submission_file> di level <article>
                    # file_id WAJIB sama dengan id pada <file> agar OJS 3.4 mengenali file utama
                    sub_file = ET.SubElement(ojs3_art, "submission_file", {
                        "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                        "id": str(current_file_id),
                        "file_id": str(current_file_id),
                        "stage": "proof",
                        "genre": "Article Text",
                        "viewable": "false"
                    })
                    
                    ET.SubElement(sub_file, "name", {"locale": art_locale}).text = fn
                    
                    # extension wajib diisi, jika kosong OJS 3.4 menyimpan file sebagai .txt
                    file_node = ET.SubElement(sub_file, "file", {
                        "id": str(current_file_id),
                        "filesize": str(file_size),
                        "extension": ext
                    })
                    
                    # Pada OJS 3.4, <embed> HANYA boleh memiliki encoding dan mime_type (TIDAK boleh ada atribut filename)
                    emb_node = ET.SubElement(file_node, "embed", {
                        "encoding": "base64",
                        "mime_type": mime
                    })
                    emb_node.text = base64_data

                    galleys_to_create.append({
                        "file_id": str(current_file_id),
                        "label": label_text,
                        "doi": galley_doi_elem.text.strip() if galley_doi_elem is not None and galley_doi_elem.text else None
                    })

            # Cari author mana yang primary_contact (default ke author pertama jika tidak ada)
            art_authors = ojs2_art.findall("author")
            primary_idx = 0
            for idx, a in enumerate(art_authors):
                if a.attrib.get("primary_contact", "false").lower() == "true":
                    primary_idx = idx
                    break
            
            primary_author_xml_id = str(author_id_counter + primary_idx)

            # Buat <publication> (Model Versi Naskah di OJS 3.4)
            # Pada OJS 3.4, <publication> TIDAK boleh memiliki atribut 'locale'
            # primary_contact_id WAJIB merujuk ke id author agar foreign key publications_primary_contact_id tidak error
            pub_attrs = {
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                "version": "1",
                "status": "3",  # 3 = STATUS_PUBLISHED
                "date_published": pub_date_str,
                "section_ref": sec_abbrev,
                "seq": str(article_seq),
                "access_status": "0"
            }
            if art_authors:
                pub_attrs["primary_contact_id"] = primary_author_xml_id

            ojs3_pub = ET.SubElement(ojs3_art, "publication", pub_attrs)

            # Internal ID publikasi (wajib untuk menghubungkan submission ke current_publication_id)
            int_id = ET.SubElement(ojs3_pub, "id", {"type": "internal", "advice": "ignore"})
            int_id.text = str(article_seq)

            # DOI Artikel
            art_doi = ojs2_art.find("./id[@type='doi']")
            if art_doi is not None and art_doi.text:
                id_doi = ET.SubElement(ojs3_pub, "id", {"type": "doi"})
                id_doi.text = art_doi.text.strip()

            # Judul Artikel
            art_title = ojs2_art.find("title")
            if art_title is not None and art_title.text:
                t_loc = normalize_locale(art_title.attrib.get("locale", art_locale))
                t_node = ET.SubElement(ojs3_pub, "title", {"locale": t_loc})
                t_node.text = art_title.text.strip()

            # Abstrak Artikel
            art_abs = ojs2_art.find("abstract")
            if art_abs is not None and art_abs.text:
                a_loc = normalize_locale(art_abs.attrib.get("locale", art_locale))
                a_node = ET.SubElement(ojs3_pub, "abstract", {"locale": a_loc})
                a_node.text = art_abs.text.strip()

            # Kata Kunci / Subject (Indexing)
            indexing_subject = ojs2_art.find(".//subject")
            if indexing_subject is not None and indexing_subject.text:
                raw_subjects = indexing_subject.text.strip().split(";")
                sub_loc = normalize_locale(indexing_subject.attrib.get("locale", art_locale))
                subjects_elem = ET.SubElement(ojs3_pub, "subjects", {"locale": sub_loc})
                for s in raw_subjects:
                    s_clean = s.strip()
                    if s_clean:
                        ET.SubElement(subjects_elem, "subject").text = s_clean

            # Penulis (Authors)
            authors_elem = ET.SubElement(ojs3_pub, "authors", {
                "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance"
            })
            
            author_seq = 1
            for idx, ojs2_auth in enumerate(art_authors):
                is_primary = (idx == primary_idx)
                # Pada OJS 3.4, atribut 'id' WAJIB ada di elemen <author>
                auth_attrs = {
                    "id": str(author_id_counter),
                    "user_group_ref": "Author",
                    "include_in_browse": "true",
                    "seq": str(author_seq)
                }
                author_id_counter += 1

                if is_primary:
                    auth_attrs["primary_contact"] = "true"

                ojs3_auth = ET.SubElement(authors_elem, "author", auth_attrs)

                fn = ojs2_auth.find("firstname")
                mn = ojs2_auth.find("middlename")
                ln = ojs2_auth.find("lastname")
                af = ojs2_auth.find("affiliation")
                country = ojs2_auth.find("country")
                em = ojs2_auth.find("email")
                bio = ojs2_auth.find("biography")

                # Gabungkan First Name & Middle Name menjadi Given Name (Standar OJS 3)
                first_str = fn.text.strip() if fn is not None and fn.text else ""
                mid_str = mn.text.strip() if mn is not None and mn.text else ""
                given_name_str = f"{first_str} {mid_str}".strip() if mid_str else first_str

                if given_name_str:
                    gn = ET.SubElement(ojs3_auth, "givenname", {"locale": art_locale})
                    gn.text = given_name_str

                if ln is not None and ln.text:
                    family_str = ln.text.strip()
                    fn_node = ET.SubElement(ojs3_auth, "familyname", {"locale": art_locale})
                    fn_node.text = family_str

                if af is not None and af.text:
                    af_loc = normalize_locale(af.attrib.get("locale", art_locale))
                    af_node = ET.SubElement(ojs3_auth, "affiliation", {"locale": af_loc})
                    af_node.text = af.text.strip()

                if country is not None and country.text:
                    ET.SubElement(ojs3_auth, "country").text = country.text.strip()

                if em is not None and em.text:
                    ET.SubElement(ojs3_auth, "email").text = em.text.strip()

                if bio is not None and bio.text:
                    bio_loc = normalize_locale(bio.attrib.get("locale", art_locale))
                    bio_node = ET.SubElement(ojs3_auth, "biography", {"locale": bio_loc})
                    bio_node.text = bio.text.strip()

                author_seq += 1

            # Article Galley (PDF Representation)
            galley_seq = 1
            for g in galleys_to_create:
                galley_elem = ET.SubElement(ojs3_pub, "article_galley", {
                    "xmlns:xsi": "http://www.w3.org/2001/XMLSchema-instance",
                    "approved": "false"
                })
                if g["doi"]:
                    g_doi = ET.SubElement(galley_elem, "id", {"type": "doi"})
                    g_doi.text = g["doi"]

                ET.SubElement(galley_elem, "name", {"locale": art_locale}).text = g["label"]
                ET.SubElement(galley_elem, "seq").text = str(galley_seq)
                ET.SubElement(galley_elem, "submission_file_ref", {"id": g["file_id"]})
                galley_seq += 1

            # Pages (Paginasi)
            pages_elem = ojs2_art.find("pages")
            if pages_elem is not None and pages_elem.text:
                ET.SubElement(ojs3_pub, "pages").text = pages_elem.text.strip()

            print(f"  [OK] Artikel #{article_seq} terproses: {art_title.text[:50] if art_title is not None else 'Untitled'}...")
            article_seq += 1

    # Simpan Hasil Konversi
    print(f"[INFO] Menyimpan file hasil konversi ke: {output_path}")
    new_tree = ET.ElementTree(ojs3_issue)
    
    # Indentasi agar rapi dibaca
    if hasattr(ET, "indent"):
        ET.indent(new_tree, space="  ")
        
    new_tree.write(output_path, encoding="utf-8", xml_declaration=True)
    print(f"[SUKSES] Berhasil mengonversi total {article_seq - 1} artikel ke format OJS 3.4.0-9!")
    return True

if __name__ == "__main__":
    input_file = r"f:\Downloads\issues.xml"
    output_file = r"f:\Downloads\issues_ojs34.xml"
    
    if len(sys.argv) > 1:
        input_file = sys.argv[1]
    if len(sys.argv) > 2:
        output_file = sys.argv[2]
        
    convert_ojs2_to_ojs34(input_file, output_file)
