"""Unit tests for seo-schema validate + generate. stdlib unittest."""

import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from schema import generate, validate  # noqa: E402


def crawl(url, structured_data):
    return {"ok": True, "data": {"site": {}, "pages": [
        {"url": url, "structured_data": structured_data}]}}


class ValidateTest(unittest.TestCase):
    def test_homepage_with_org_website_no_recommend(self):
        sd = [{"@context": "https://schema.org", "@type": "Organization", "name": "X", "url": "https://x.com"},
              {"@context": "https://schema.org", "@type": "WebSite", "name": "X", "url": "https://x.com"}]
        r = validate(crawl("https://x.com/", sd))
        self.assertEqual(r["recommended_types"], [])
        self.assertIn("Organization", r["present_types"])

    def test_homepage_without_schema_recommends_org_website(self):
        r = validate(crawl("https://x.com/", []))
        self.assertEqual(set(r["recommended_types"]), {"Organization", "WebSite"})
        self.assertIn("schema_recommend", {f["id"] for f in r["findings"]})

    def test_missing_type_flagged(self):
        r = validate(crawl("https://x.com/p", [{"name": "no type here"}]))
        self.assertIn("schema_no_type", {f["id"] for f in r["findings"]})

    def test_missing_required_field(self):
        r = validate(crawl("https://x.com/p", [{"@type": "Organization", "name": "X"}]))  # missing url
        ids = {f["id"] for f in r["findings"]}
        self.assertIn("schema_missing_field", ids)

    def test_faqpage_deprecated_richresult(self):
        sd = [{"@type": "FAQPage", "mainEntity": [{"@type": "Question", "name": "q",
               "acceptedAnswer": {"@type": "Answer", "text": "a"}}]}]
        r = validate(crawl("https://x.com/faq", sd))
        self.assertIn("schema_deprecated_richresult", {f["id"] for f in r["findings"]})

    def test_graph_expansion(self):
        sd = [{"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "name": "X", "url": "https://x.com"},
            {"@type": "WebSite", "name": "X", "url": "https://x.com"}]}]
        r = validate(crawl("https://x.com/", sd))
        self.assertEqual(set(r["present_types"]), {"Organization", "WebSite"})


class GenerateTest(unittest.TestCase):
    def test_generate_org(self):
        out = generate("Organization", None)
        self.assertEqual(out["@type"], "Organization")
        self.assertEqual(out["@context"], "https://schema.org")

    def test_generate_with_overrides(self):
        out = generate("WebSite", {"name": "Orkas", "url": "https://orkas.ai"})
        self.assertEqual(out["name"], "Orkas")
        self.assertEqual(out["url"], "https://orkas.ai")

    def test_generate_unknown_raises(self):
        with self.assertRaises(ValueError):
            generate("Nonsense", None)


class MultiTypeValidateTest(unittest.TestCase):
    def test_multi_type_node_satisfies_all_required(self):
        node = {"@context": "https://schema.org", "@type": ["Organization", "WebSite"],
                "name": "X", "url": "https://x.com"}
        r = validate(crawl("https://x.com/", [node]))
        self.assertEqual(set(r["present_types"]), {"Organization", "WebSite"})
        self.assertEqual(r["recommended_types"], [])
        self.assertEqual(r["findings"], [])

    def test_multi_type_missing_per_type(self):
        # Article + BlogPosting both require headline → one finding each.
        r = validate(crawl("https://x.com/post", [{"@type": ["Article", "BlogPosting"]}]))
        missing = [f for f in r["findings"] if f["id"] == "schema_missing_field"]
        self.assertEqual(len(missing), 2)


class UnknownTypeValidateTest(unittest.TestCase):
    def test_unknown_type_no_missing_field(self):
        r = validate(crawl("https://x.com/p", [{"@type": "Recipe", "name": "Cake"}]))
        ids = {f["id"] for f in r["findings"]}
        self.assertNotIn("schema_missing_field", ids)  # Recipe has no required set
        self.assertIn("Recipe", r["present_types"])

    def test_numeric_type_no_exception(self):
        r = validate(crawl("https://x.com/p", [{"@type": 123}]))
        self.assertEqual(r["present_types"], ["123"])


class RecommendTest(unittest.TestCase):
    def test_subpage_recommends_breadcrumb(self):
        r = validate(crawl("https://x.com/docs/", []))
        self.assertEqual(r["recommended_types"], ["BreadcrumbList"])
        self.assertIn("schema_recommend", {f["id"] for f in r["findings"]})

    def test_no_trailing_slash_is_homepage(self):
        r = validate(crawl("https://x.com", []))
        self.assertEqual(set(r["recommended_types"]), {"Organization", "WebSite"})


class GenerateIsolationTest(unittest.TestCase):
    def test_generate_isolated_between_calls(self):
        o1 = generate("Organization", None)
        o1["sameAs"].append("https://extra.example")
        o1["name"] = "Mutated"
        o2 = generate("Organization", None)
        self.assertEqual(o2["name"], "<ORG NAME>")  # deep-copied template, unaffected
        self.assertEqual(len(o2["sameAs"]), 2)


class HowToValidateTest(unittest.TestCase):
    def test_howto_deprecated_and_missing_step(self):
        r = validate(crawl("https://x.com/how", [{"@type": "HowTo", "name": "Do X"}]))
        ids = {f["id"] for f in r["findings"]}
        self.assertIn("schema_missing_field", ids)          # missing step
        self.assertIn("schema_deprecated_richresult", ids)  # HowTo deprecated


class MediumFixTest(unittest.TestCase):
    def test_empty_required_value_is_flagged(self):
        # Present-but-empty required props are as invalid as absent ones.
        r = validate(crawl("https://x.com/", [{"@type": "Organization", "name": "", "url": ""}]))
        self.assertIn("schema_missing_field", {f["id"] for f in r["findings"]})

    def test_graph_as_dict_extracts_inner_node(self):
        # A single-object @graph (not a list) must still yield its inner node.
        r = validate(crawl("https://x.com/p", [{"@context": "https://schema.org",
            "@graph": {"@type": "Organization", "name": "X", "url": "https://x.com"}}]))
        self.assertIn("Organization", r["present_types"])
        self.assertNotIn("schema_no_type", {f["id"] for f in r["findings"]})


class EmbeddedNodeValidateTest(unittest.TestCase):
    def test_nested_product_missing_name_is_linted(self):
        sd = [{"@type": "WebPage", "mainEntity": {"@type": "Product"}}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertIn("Product", r["present_types"])
        self.assertIn("Product lacks name", [f["evidence"] for f in r["findings"]])

    def test_nested_breadcrumb_prevents_duplicate_recommendation(self):
        sd = [{"@type": "WebPage", "breadcrumb": {"@type": "BreadcrumbList",
               "itemListElement": [{"@type": "ListItem", "position": 1}]}}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertEqual(r["recommended_types"], [])
        self.assertEqual(set(r["present_types"]), {"WebPage", "BreadcrumbList", "ListItem"})

    def test_deep_arrays_and_graphs_are_walked_once(self):
        sd = [{"@graph": [{"@type": "WebPage", "mainEntity": [
            {"@type": "Product", "brand": {"@type": "Organization", "name": "X"}},
            {"@graph": {"@type": "Article"}}]}]}]
        r = validate(crawl("https://x.com/p", sd))
        missing = [f["evidence"] for f in r["findings"] if f["id"] == "schema_missing_field"]
        self.assertCountEqual(missing, ["Product lacks name", "Organization lacks url", "Article lacks headline"])
        self.assertNotIn("schema_no_type", {f["id"] for f in r["findings"]})

    def test_context_definitions_and_json_literals_are_not_nodes(self):
        sd = [{"@context": {"example": {"@type": "Product"}}, "@type": "WebPage",
               "data": {"@type": "@json", "@value": {"@type": "BreadcrumbList"}},
               "name": {"@value": "Page", "@language": "en"}}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertEqual(r["present_types"], ["WebPage"])
        self.assertEqual(r["recommended_types"], ["BreadcrumbList"])
        self.assertNotIn("schema_no_type", {f["id"] for f in r["findings"]})

    def test_node_references_and_untyped_property_objects_are_not_linted(self):
        sd = [{"@id": "#page"}, {"@type": "WebPage", "author": {"@id": "#author"},
               "details": {"name": "not a typed node", "part": {"@type": "Product"}}}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertNotIn("schema_no_type", {f["id"] for f in r["findings"]})
        self.assertIn("Product", r["present_types"])

    def test_top_level_and_graph_typeless_warnings_are_preserved(self):
        sd = [{"name": "top"}, {"@graph": [{"name": "graph"}]}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertEqual(sum(f["id"] == "schema_no_type" for f in r["findings"]), 2)

    def test_typed_graph_wrapper_is_also_validated(self):
        sd = [{"@type": "Organization", "name": "X", "@graph": {"@type": "Product"}}]
        r = validate(crawl("https://x.com/p", sd))
        missing = [f["evidence"] for f in r["findings"] if f["id"] == "schema_missing_field"]
        self.assertCountEqual(missing, ["Organization lacks url", "Product lacks name"])

    def test_list_and_set_containers_are_not_typeless_nodes(self):
        sd = [{"@type": "WebPage", "parts": {"@list": [{"@type": "Article"}]},
               "related": {"@set": [{"@type": "Product"}]}}]
        r = validate(crawl("https://x.com/p", sd))
        self.assertNotIn("schema_no_type", {f["id"] for f in r["findings"]})
        self.assertEqual(set(r["present_types"]), {"WebPage", "Article", "Product"})


if __name__ == "__main__":
    unittest.main()
