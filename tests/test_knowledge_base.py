"""Chapter 31 — your knowledge base: parse, chunk, embed, store, retrieve, answer.

Documents are read on this computer and nothing is sent anywhere to add
one. A question retrieves only parts that hold at least half its words; with
none, the model isn't asked and nothing is guessed. What the model says is
checked: a fact must cite a part that holds it, or it's shown as the
model's own suggestion, never as something from your documents.
"""
from __future__ import annotations

import json

import pytest

from jarvis.ai import provider
from jarvis.app import bridge, config
from jarvis.routing.router import fast_route
from jarvis.store import knowledge
from jarvis.tools.registry import FUNCTIONS, TOOL_SCHEMAS


def make_pdf(pages: list[str]) -> bytes:
    """A small real PDF, one line of text per line given."""
    objects, kids, next_id = {}, [], 4
    for text in pages:
        page_id, content_id = next_id, next_id + 1
        next_id += 2
        kids.append(page_id)
        stream = "BT /F1 11 Tf 50 750 Td 14 TL " + " ".join(f"({line}) Tj T*" for line in text.split("\n")) + " ET"
        objects[content_id] = f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream"
        objects[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents {content_id} 0 R "
                            "/Resources << /Font << /F1 3 0 R >> >> >>")
    objects[1] = "<< /Type /Catalog /Pages 2 0 R >>"
    objects[2] = f"<< /Type /Pages /Kids [{' '.join(f'{k} 0 R' for k in kids)}] /Count {len(pages)} >>"
    objects[3] = "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"
    out, offsets = b"%PDF-1.4\n", {}
    for i in sorted(objects):
        offsets[i] = len(out)
        out += f"{i} 0 obj\n{objects[i]}\nendobj\n".encode()
    xref, size = len(out), max(objects) + 1
    out += f"xref\n0 {size}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offsets[i]:010d} 00000 n \n".encode() for i in range(1, size))
    return out + f"trailer\n<< /Size {size} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()


CORPUS = {
    "hackathon.md": "# Blood Bridge hackathon\n\nThe Blood Bridge hackathon deadline is 14 March 2026. Submissions go "
                    "through Devfolio, and the demo video must be under three minutes.\n\nJudging is on impact, "
                    "technical depth and the live demo.",
    "stack.md": "# Blood Bridge stack\n\nThe backend uses Node.js with MongoDB Atlas as the database. Emergency "
                "requests are matched to donors within 5 km using geospatial queries.\n\nThe frontend is React "
                "with Tailwind. Deployment is on Render's free tier.",
    "internship.txt": "My internship at Acme Analytics runs from June to August 2026.\n\nThe stipend is paid "
                      "monthly. My manager is Priya and standups are at 10 am.",
    "recipes.txt": "Masala chai: boil water with ginger and cardamom, add tea leaves, milk and sugar, simmer for "
                   "two minutes.\n\nPoha: rinse flattened rice, temper mustard seeds and curry leaves, add onion, "
                   "turmeric and peanuts.",
}


@pytest.fixture
def no_model(monkeypatch):
    """Any call to the model fails the test."""
    def refuse(*_a, **_k):
        raise AssertionError("the model was asked")
    monkeypatch.setattr(provider, "call_gemini", refuse)
    monkeypatch.setattr(provider, "ask_text", refuse)


@pytest.fixture
def corpus(workspace, no_model):
    for name, text in CORPUS.items():
        (workspace / name).write_text(text, encoding="utf-8")
        assert knowledge.add_document(name).startswith("Added")
    return workspace


@pytest.fixture
def model(monkeypatch):
    """The model, answering with whatever `reply` holds; records prompts."""
    said = {"reply": {"facts": [], "suggestion": ""}, "prompts": []}

    def ask(prompt, system=None, empty=""):
        said["prompts"].append(prompt)
        if isinstance(said["reply"], Exception):
            raise said["reply"]
        return said["reply"] if isinstance(said["reply"], str) else json.dumps(said["reply"])
    monkeypatch.setattr(provider, "ask_text", ask)
    return said


# ================================================================== parse

class TestParsing:
    def test_text_and_markdown(self, workspace):
        (workspace / "a.md").write_text("# Title\n\nHello there.", encoding="utf-8")
        assert knowledge.parse(workspace / "a.md") == [(None, "# Title\n\nHello there.")]

    def test_html_without_its_scripts(self, workspace):
        (workspace / "p.html").write_text("<html><script>var secret=1</script><p>Visible &amp; kept</p>"
                                          "<style>p{}</style></html>", encoding="utf-8")
        (page, text), = knowledge.parse(workspace / "p.html")
        assert "Visible & kept" in text and "secret" not in text and "p{}" not in text

    def test_a_pdf_keeps_its_pages(self, workspace):
        (workspace / "plan.pdf").write_bytes(make_pdf(["The budget is 40000 rupees.", "The venue is Prayagraj."]))
        pages = knowledge.parse(workspace / "plan.pdf")
        assert [p for p, _ in pages] == [1, 2] and "Prayagraj" in pages[1][1]

    def test_a_word_document(self, workspace):
        docx = pytest.importorskip("docx")
        document = docx.Document()
        document.add_paragraph("The client meeting is on Monday.")
        document.save(str(workspace / "brief.docx"))
        assert "client meeting is on Monday" in knowledge.parse(workspace / "brief.docx")[0][1]

    def test_what_it_cant_read_is_said(self, workspace, monkeypatch):
        (workspace / "a.exe").write_bytes(b"MZ")
        with pytest.raises(ValueError, match="can't read .exe files"):
            knowledge.parse(workspace / "a.exe")
        (workspace / "big.txt").write_text("x" * 50, encoding="utf-8")
        monkeypatch.setattr(knowledge, "MAX_FILE_BYTES", 10)
        with pytest.raises(ValueError, match="too big to add"):
            knowledge.parse(workspace / "big.txt")
        (workspace / "bad.pdf").write_bytes(b"not a pdf")
        with pytest.raises(ValueError, match="couldn't read that PDF"):
            monkeypatch.setattr(knowledge, "MAX_FILE_BYTES", 10**6)
            knowledge.parse(workspace / "bad.pdf")

    def test_only_inside_the_workspace(self, workspace, tmp_path):
        outside = tmp_path / "private.txt"
        outside.write_text("nope", encoding="utf-8")
        assert "outside the workspace" in knowledge.add_document(str(outside))
        assert knowledge.documents() == []


# ================================================================== chunk

class TestChunking:
    def test_short_text_is_one_part(self):
        assert knowledge.chunk([(None, "One.\n\nTwo.")]) == [{"page": None, "text": "One. Two."}]

    def test_long_text_is_parts_of_bounded_size_that_overlap(self):
        paragraphs = [f"Paragraph {i} talks about topic{i} in some detail, with enough words to end{i}." for i in range(40)]
        parts = knowledge.chunk([(None, "\n\n".join(paragraphs))])
        assert len(parts) > 3
        assert all(len(p["text"]) <= knowledge.PART_CHARS + knowledge.OVERLAP + 100 for p in parts)
        for before, after in zip(parts, parts[1:]):
            assert before["text"][-40:].split()[-1] in after["text"], "each part carries the tail of the last"
        joined = " ".join(p["text"] for p in parts)
        assert all(f"topic{i}" in joined for i in range(40)), "nothing is lost"

    def test_one_huge_paragraph_is_still_cut(self):
        parts = knowledge.chunk([(None, "word " * 1000)])
        assert len(parts) > 4 and max(len(p["text"]) for p in parts) <= knowledge.PART_CHARS

    def test_a_part_never_spans_two_pages(self):
        parts = knowledge.chunk([(1, "Alpha on page one."), (2, "Beta on page two.")])
        assert parts == [{"page": 1, "text": "Alpha on page one."}, {"page": 2, "text": "Beta on page two."}]

    def test_empty_text_has_no_parts_and_the_count_is_capped(self, monkeypatch):
        assert knowledge.chunk([(None, "  \n\n ")]) == []
        monkeypatch.setattr(knowledge, "MAX_PARTS", 3)
        assert len(knowledge.chunk([(None, "\n\n".join("x" * 800 for _ in range(10)))])) == 3


# ================================================================== embed

class TestEmbedding:
    def test_stems_and_pairs_without_little_words(self):
        assert knowledge.terms("The deadlines are matching") == knowledge.terms("deadline matched")
        assert knowledge.terms("deployment") == knowledge.terms("deployed") == knowledge.terms("deploying")
        assert knowledge.terms("boxes matches") == ["box", "match", "box_match"]
        assert knowledge.embed("chai chai tea") == {"chai": 2, "tea": 1, "chai_chai": 1, "chai_tea": 1}

    def test_adding_sends_nothing_anywhere(self, corpus):
        assert len(knowledge.documents()) == 4          # no_model would have failed it


# ================================================================== store

class TestTheStore:
    def test_added_once_and_then_unchanged(self, corpus):
        assert knowledge.add_document("stack.md") == "stack.md is already in your knowledge base, unchanged."
        assert len(knowledge.documents()) == 4

    def test_a_changed_file_is_read_again(self, corpus):
        (corpus / "stack.md").write_text("The backend moved to PostgreSQL.", encoding="utf-8")
        assert knowledge.add_document("stack.md").startswith("Updated stack.md: it had changed")
        assert [p["name"] for p in knowledge.retrieve("postgresql backend")] == ["stack.md"]
        assert knowledge.retrieve("mongodb atlas") == [], "the old parts are gone"

    def test_a_pdf_says_its_pages(self, workspace, no_model):
        (workspace / "plan.pdf").write_bytes(make_pdf(["The budget is 40000 rupees.", "The venue is Prayagraj."]))
        assert knowledge.add_document("plan.pdf") == "Added plan.pdf to your knowledge base (2 pages, 2 parts)."
        (hit,) = knowledge.retrieve("where is the venue")
        assert (hit["name"], hit["page"]) == ("plan.pdf", 2)

    def test_nothing_readable_adds_nothing(self, workspace):
        (workspace / "blank.txt").write_text("   \n", encoding="utf-8")
        assert knowledge.add_document("blank.txt") == "blank.txt has no text I can read, so nothing was added."
        assert knowledge.add_document("missing.txt").startswith("I can't find ")
        assert knowledge.add_document(" ") == "Tell me which file or folder to add."
        assert knowledge.documents() == []

    def test_a_folder_adds_what_it_can_read(self, workspace, no_model):
        (workspace / "notes").mkdir()
        (workspace / "notes" / "a.md").write_text("Alpha notes.", encoding="utf-8")
        (workspace / "notes" / "b.txt").write_text("Beta notes.", encoding="utf-8")
        (workspace / "notes" / "photo.png").write_bytes(b"\x89PNG")
        (workspace / "notes" / "node_modules").mkdir()
        (workspace / "notes" / "node_modules" / "x.md").write_text("vendored", encoding="utf-8")
        assert knowledge.add_document("notes") == "From notes: 2 added."
        assert [d["name"] for d in knowledge.documents()] == ["a.md", "b.txt"]
        assert knowledge.add_document("notes") == "From notes: 2 unchanged."

    def test_removing_takes_it_out_and_leaves_the_file(self, corpus):
        assert knowledge.remove_document("recipes") == "No document called recipes in your knowledge base."
        assert knowledge.remove_document("RECIPES.TXT") == \
            "Removed recipes.txt from your knowledge base. The file itself is untouched."
        assert (corpus / "recipes.txt").exists() and knowledge.retrieve("masala chai") == []

    def test_listing(self, corpus):
        assert knowledge.list_documents() == ("4 documents: hackathon.md (1 part); internship.txt (1 part); "
                                              "recipes.txt (1 part); stack.md (1 part).")

    def test_its_in_the_memory_folder_and_the_log_has_no_text(self, corpus):
        assert knowledge.DB_PATH.parent == config.MEMORY_DIR and knowledge.DB_PATH.exists()
        logged = config.LOG_FILE.read_text(encoding="utf-8") if config.LOG_FILE.exists() else ""
        assert "Devfolio" not in logged and "Priya" not in logged


# =============================================================== retrieve

class TestRetrievalQuality:
    @pytest.mark.parametrize("question,document", [
        ("when is the hackathon deadline?", "hackathon.md"),
        ("what database does blood bridge use", "stack.md"),
        ("which database", "stack.md"),
        ("where is it deployed", "stack.md"),
        ("who is my manager", "internship.txt"),
        ("how is the stipend paid", "internship.txt"),
        ("how do I make masala chai", "recipes.txt"),
        ("how is the demo judged", "hackathon.md"),
    ])
    def test_the_right_document_comes_first(self, corpus, question, document):
        assert knowledge.retrieve(question)[0]["name"] == document

    @pytest.mark.parametrize("question", ["who won the world cup", "what is the deadline for my tax return",
                                          "the of a is", "", "quantum chromodynamics lecture"])
    def test_an_unrelated_question_retrieves_nothing(self, corpus, question):
        assert knowledge.retrieve(question) == []

    def test_a_word_shared_by_many_counts_for_less(self, corpus):
        found = knowledge.retrieve("blood bridge demo")
        assert [f["name"] for f in found] == ["hackathon.md", "stack.md"]
        assert found[0]["score"] > found[1]["score"]

    def test_a_rare_word_outweighs_a_common_one_said_often(self, workspace, no_model):
        docs = {"a.txt": "Meeting meeting meeting meeting meeting notes, and one line about the visa.",
                "b.txt": "Visa appointment: the visa interview is right after the meeting.",
                "c.txt": "Meeting with the design team.", "d.txt": "Meeting about the budget.",
                "e.txt": "Weekly meeting recap."}
        for name, text in docs.items():
            (workspace / name).write_text(text, encoding="utf-8")
            knowledge.add_document(name)
        assert [f["name"] for f in knowledge.retrieve("visa meeting")][:2] == ["b.txt", "a.txt"]

    def test_at_most_four_parts(self, workspace, no_model):
        for i in range(8):
            (workspace / f"n{i}.txt").write_text(f"Meeting notes number {i} about the budget.", encoding="utf-8")
            knowledge.add_document(f"n{i}.txt")
        assert len(knowledge.retrieve("budget meeting")) == knowledge.TOP == 4


# ================================================================= answer

class TestAnswering:
    def test_a_fact_found_is_a_retrieved_fact_with_its_source(self, corpus, model):
        model["reply"] = {"facts": [{"text": "The hackathon deadline is 14 March 2026.", "sources": [1]}],
                          "suggestion": "Aim to submit a day early."}
        said = knowledge.ask_documents("when is the hackathon deadline?")
        assert said == ("RETRIEVED FACT: The hackathon deadline is 14 March 2026. [hackathon.md, part 1]\n"
                        "GENERATED SUGGESTION (the model's own, not in your documents): Aim to submit a day early.")

    def test_a_fact_the_parts_dont_hold_is_shown_as_the_models(self, corpus, model):
        model["reply"] = {"facts": [{"text": "Winners get a cash prize of 50000 rupees and cloud credits.",
                                     "sources": [1]}], "suggestion": ""}
        said = knowledge.ask_documents("when is the hackathon deadline?")
        assert "RETRIEVED FACT" not in said
        assert said.endswith("GENERATED SUGGESTION (the model's own, not in your documents): "
                             "Winners get a cash prize of 50000 rupees and cloud credits.")

    @pytest.mark.parametrize("sources", [[], [9], ["1"], None])
    def test_a_fact_without_a_real_citation_is_not_retrieved(self, corpus, model, sources):
        model["reply"] = {"facts": [{"text": "The hackathon deadline is 14 March 2026.", "sources": sources}]}
        said = knowledge.ask_documents("when is the hackathon deadline?")
        assert "RETRIEVED FACT" not in said and "GENERATED SUGGESTION" in said

    def test_only_the_parts_retrieved_go_to_the_model(self, corpus, model):
        knowledge.ask_documents("when is the hackathon deadline?")
        (prompt,) = model["prompts"]
        assert "[1] (hackathon.md, part 1)" in prompt and "Devfolio" in prompt
        for elsewhere in ("Priya", "cardamom", "MongoDB"):
            assert elsewhere not in prompt

    def test_nothing_retrieved_asks_nothing_and_guesses_nothing(self, corpus, no_model):
        assert knowledge.ask_documents("who won the world cup?") == "Nothing in your documents answers that. I didn't guess."

    def test_an_empty_knowledge_base_says_so(self, no_model):
        assert knowledge.ask_documents("anything").startswith("Your knowledge base is empty.")

    @pytest.mark.parametrize("reply", [RuntimeError("I can't reach the internet right now."), "not json", "[1, 2]"])
    def test_without_the_model_the_passages_are_the_answer(self, corpus, model, reply):
        model["reply"] = reply
        said = knowledge.ask_documents("when is the hackathon deadline?")
        assert said.startswith("I couldn't get an answer from the model, so here are the passages that match:")
        assert "RETRIEVED [hackathon.md, part 1]: # Blood Bridge hackathon The Blood Bridge hackathon deadline" in said

    def test_passages_found_that_dont_answer_are_named(self, corpus, model):
        model["reply"] = {"facts": [], "suggestion": ""}
        assert knowledge.ask_documents("when is the hackathon deadline?") == \
            "The passages I found don't answer it: hackathon.md, part 1."

    def test_a_pdf_fact_cites_its_page(self, workspace, model):
        (workspace / "plan.pdf").write_bytes(make_pdf(["The budget is 40000 rupees.", "The venue is Prayagraj."]))
        knowledge.add_document("plan.pdf")
        model["reply"] = {"facts": [{"text": "The venue is Prayagraj.", "sources": [1]}]}
        assert knowledge.ask_documents("where is the venue?") == "RETRIEVED FACT: The venue is Prayagraj. [plan.pdf, page 2]"

    def test_searching_uses_no_model(self, corpus, no_model):
        assert knowledge.search_documents("stipend").startswith("RETRIEVED [internship.txt, part 1]: My internship")
        assert knowledge.search_documents("world cup") == "Nothing in your documents matches “world cup”."


# =============================================================== reaching

class TestReachingIt:
    def test_by_command(self, corpus, model, monkeypatch):
        (corpus / "Extra Notes.md").write_text("The Wi-Fi name is CampusNet.", encoding="utf-8")
        assert fast_route("add Extra Notes.md to my knowledge base").startswith("Added Extra Notes.md")
        assert fast_route("what's in my knowledge base?").startswith("5 documents:")
        assert fast_route("search my documents for stipend").startswith("RETRIEVED [internship.txt")
        model["reply"] = {"facts": [{"text": "My manager is Priya.", "sources": [1]}]}
        assert fast_route("according to my notes, who is my manager?") == \
            "RETRIEVED FACT: My manager is Priya. [internship.txt, part 1]"
        assert fast_route("ask my knowledge base who is my manager").startswith("RETRIEVED FACT")
        assert fast_route("remove Extra Notes.md from my knowledge base").startswith("Removed Extra Notes.md")

    @pytest.mark.parametrize("command", ["add milk to my notes", "add this to my documents",
                                         "show my documents folder"])
    def test_words_that_mean_something_else_are_left_alone(self, monkeypatch, command):
        monkeypatch.setattr(knowledge, "add_document", lambda *_a: pytest.fail("added"))
        monkeypatch.setattr(knowledge, "list_documents", lambda *_a: pytest.fail("listed"))
        fast_route(command)

    def test_the_tools(self):
        for name in ("add_document", "list_documents", "remove_document", "search_documents", "ask_documents"):
            assert FUNCTIONS[name] is getattr(knowledge, name)
        described = {t["name"]: t["description"] for t in TOOL_SCHEMAS}
        assert "RETRIEVED FACT" in described["ask_documents"] and "GENERATED SUGGESTION" in described["ask_documents"]
        assert "Uses no model" in described["search_documents"]

    def test_the_memory_section_lists_them(self, corpus, monkeypatch):
        class Quiet:
            muted, running, brain = True, False, None
        monkeypatch.setattr(bridge.stats, "snapshot", lambda *_a, **_k: {})
        seen = bridge.Api(assistant=Quiet()).memory_view()
        assert [d["name"] for d in seen["documents"]] == ["hackathon.md", "internship.txt", "recipes.txt", "stack.md"]
        assert set(seen["documents"][0]) == {"name", "pages", "parts", "added"}, "no paths or text"


import _ui  # noqa: E402


class TestTheMemorySectionRow:
    @pytest.fixture(autouse=True)
    def browser_ok(self):
        if not _ui.available():
            pytest.skip("Playwright isn't installed")

    def _row(self, documents):
        snapshot = {"facts": [], "contacts": [], "log": {"count": 0, "keep": 200, "recent": []},
                    "resume": {"ready": False, "name": "", "skills": 0, "projects": 0},
                    "jobs": {"total": 0, "applied": 0}, "folder": "D:/little/memory"}
        if documents is not None:
            snapshot["documents"] = documents
        opening = {"status": "listening", "lines": [], "tasks": {"v": 0, "changed": []}}
        check = "() => { const r = document.querySelector('#memAbout [data-docs]'); return r && r.textContent; }"
        result, errors = _ui.open_panel(lambda page: page.evaluate(check), route="memory",
                                        script=_ui.bridge(opening) + "window.__memory = %s;" % json.dumps(snapshot))
        if result is _ui.NO_BROWSER:
            pytest.skip("no browser to render the panel with")
        assert errors == [], errors
        return result

    def test_listed_by_name(self):
        assert self._row([{"name": "plan.pdf", "pages": 2, "parts": 2, "added": "x"},
                          {"name": "a.md", "pages": None, "parts": 1, "added": "x"}]) == \
            "Your documentsplan.pdf (2 parts), a.md (1 part)"

    def test_none_yet_says_how(self):
        assert self._row([]) == "Your documentsNone yet. Say: add notes.pdf to my knowledge base"

    def test_an_older_snapshot_shows_no_row(self):
        assert self._row(None) is None
