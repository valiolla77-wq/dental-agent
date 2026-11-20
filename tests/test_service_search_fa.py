"""Deterministic Persian service-search normalization and ranking tests."""

import unittest

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.models.base import Base
from app.models.dental_service import DentalService
from app.services import dental_service_service


class PersianServiceSearchTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.factory = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.factory() as db:
            self.cleaning = DentalService(
                name="جرم‌گیری و پاکسازی",
                description="پاکسازی جرم و پلاک دندان",
                is_active=True,
            )
            self.exam = DentalService(
                name="معاینه اولیه دندانپزشکی",
                description=(
                    "معاینه و بررسی اولیه دندان و لثه؛ "
                    "ارجاع درمان به دندانپزشک."
                ),
                is_active=True,
            )
            self.filling = DentalService(
                name="ترمیم دندان",
                description=(
                    "بررسی و ترمیم پوسیدگی یا آسیب دندان توسط دندانپزشک."
                ),
                is_active=True,
            )
            self.bleaching = DentalService(
                name="بلیچینگ",
                description="سفید کردن دندان.",
                is_active=True,
            )
            self.inactive = DentalService(
                name="خدمت غیرفعال",
                description="پوسیدگی غیرفعال",
                is_active=False,
            )
            db.add_all(
                [
                    self.cleaning,
                    self.exam,
                    self.filling,
                    self.bleaching,
                    self.inactive,
                ]
            )
            await db.commit()
            self.ids = {
                "cleaning": self.cleaning.id,
                "exam": self.exam.id,
                "filling": self.filling.id,
                "bleaching": self.bleaching.id,
                "inactive": self.inactive.id,
            }

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def _names(self, query, *, limit=20):
        async with self.factory() as db:
            rows = await dental_service_service.search_dental_services(
                db, query, limit=limit
            )
        return [row.name for row in rows]

    async def test_persian_characters_zwnj_and_punctuation_are_normalized(self):
        for query in (
            "دندان‌هاي پوسيده",
            "دندان‌های پوسیده",
            "  پوسيدگي، دندان  ",
            "پوسیدگیِ دندان",
        ):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertEqual(names[0], "ترمیم دندان")
                self.assertNotIn("جرم‌گیری و پاکسازی", names)

    async def test_caries_phrases_prioritize_filling(self):
        for query in (
            "پوسیدگی",
            "پوسیده",
            "پوسیدگی دندان",
        ):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertEqual(names[0], "ترمیم دندان")
                self.assertNotIn("جرم‌گیری و پاکسازی", names)
                self.assertNotIn("بلیچینگ", names)

    async def test_review_phrase_returns_exam_and_filling_only(self):
        names = await self._names("بررسی پوسیدگی")
        self.assertEqual(
            set(names),
            {"معاینه اولیه دندانپزشکی", "ترمیم دندان"},
        )

    async def test_colloquial_tooth_and_pain_phrases_find_related_services(self):
        for query in ("دندون", "دندان"):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertIn("معاینه اولیه دندانپزشکی", names)
                self.assertIn("ترمیم دندان", names)

        for query in ("درد دندان", "دندان درد", "درد"):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertEqual(names[0], "معاینه اولیه دندانپزشکی")
                self.assertIn("ترمیم دندان", names)
                self.assertNotIn("جرم‌گیری و پاکسازی", names)
                self.assertNotIn("بلیچینگ", names)

    async def test_patient_style_caries_phrases_rank_filling_first(self):
        for query in (
            "دندونم پوسیده",
            "دندونام پوسیده",
            "پوسیدگی دندان",
        ):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertEqual(
                    names[:2],
                    ["ترمیم دندان", "معاینه اولیه دندانپزشکی"],
                )
                self.assertNotIn("جرم‌گیری و پاکسازی", names)
                self.assertNotIn("بلیچینگ", names)

    async def test_pain_phrase_keeps_exam_first_and_filling_relevant(self):
        names = await self._names("دندونم درد می‌کنه")
        self.assertEqual(
            names[:2],
            ["معاینه اولیه دندانپزشکی", "ترمیم دندان"],
        )
        self.assertNotIn("جرم‌گیری و پاکسازی", names)
        self.assertNotIn("بلیچینگ", names)

    async def test_ambiguous_damage_wording_stays_available_for_clarification(self):
        for query in (
            "دندان خراب شده",
            "دندان شکسته",
            "دندانم خراب شده و نزدیک‌ترین نوبت را می‌خواهم",
        ):
            with self.subTest(query=query):
                names = await self._names(query)
                # Damage/breakage is not equated with caries without context,
                # but relevant examination/filling services remain selectable.
                self.assertEqual(
                    set(names),
                    {"معاینه اولیه دندانپزشکی", "ترمیم دندان"},
                )

    async def test_generic_words_do_not_add_unrelated_services(self):
        for query in ("فقط دندون", "فقط نوبت دندان"):
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertIn("معاینه اولیه دندانپزشکی", names)
                self.assertIn("ترمیم دندان", names)
                self.assertNotIn("جرم‌گیری و پاکسازی", names)
                self.assertNotIn("بلیچینگ", names)

    async def test_long_model_style_phrase_returns_relevant_services(self):
        names = await self._names(
            "معاینه پوسیدگی دندان، بررسی درد یا پوسیدگی"
        )
        self.assertEqual(
            names[:2],
            ["معاینه اولیه دندانپزشکی", "ترمیم دندان"],
        )
        self.assertNotIn("جرم‌گیری و پاکسازی", names)
        self.assertNotIn("بلیچینگ", names)

    async def test_unrelated_query_returns_no_services(self):
        self.assertEqual(await self._names("بیمه"), [])
        self.assertEqual(await self._names("قطعه‌سازی خودرو"), [])

    async def test_empty_or_generic_query_lists_active_services_only(self):
        expected = {
            "جرم‌گیری و پاکسازی",
            "معاینه اولیه دندانپزشکی",
            "ترمیم دندان",
            "بلیچینگ",
        }
        for query in (None, "", "   ", "خدمات مطب", "نزدیک‌ترین نوبت"):
            with self.subTest(query=query):
                self.assertEqual(set(await self._names(query)), expected)

    async def test_generic_query_respects_ranking_context_and_limit(self):
        # Generic browsing is explicit and deterministic; it never invents
        # relevance scores or returns inactive rows.
        self.assertEqual(
            set(await self._names("نوبت", limit=2)),
            {"جرم‌گیری و پاکسازی", "معاینه اولیه دندانپزشکی"},
        )
        self.assertEqual(
            len(await self._names("خدمات دندانپزشکی", limit=3)),
            3,
        )

    async def test_limit_is_applied_after_ranking(self):
        names = await self._names("پوسیدگی دندان", limit=1)
        self.assertEqual(names, ["ترمیم دندان"])

    async def test_search_does_not_mutate_stored_service_text(self):
        async with self.factory() as db:
            await dental_service_service.search_dental_services(
                db, "دندان‌هاي پوسيده"
            )
            stored = await db.scalar(
                select(DentalService).where(
                    DentalService.id == self.ids["filling"]
                )
            )
            self.assertEqual(stored.name, "ترمیم دندان")
            self.assertEqual(
                stored.description,
                "بررسی و ترمیم پوسیدگی یا آسیب دندان توسط دندانپزشک.",
            )

    async def test_inactive_service_is_never_returned(self):
        names = await self._names("پوسیدگی")
        self.assertNotIn("خدمت غیرفعال", names)

    async def test_sample_seed_catalog_handles_patient_style_queries(self):
        # These are exactly the three services created by scripts.seed_sample.py.
        # The fixture above also mirrors them, with an extra whitening row.
        cases = (
            (
                "دندون‌هام پوسیده و نزدیک‌ترین نوبت رو می‌خوام.",
                "ترمیم دندان",
                {"ترمیم دندان", "معاینه اولیه دندانپزشکی"},
            ),
            (
                "دندونام درد داره",
                "معاینه اولیه دندانپزشکی",
                {"ترمیم دندان", "معاینه اولیه دندانپزشکی"},
            ),
            (
                "جرم گیری",
                "جرم‌گیری و پاکسازی",
                {"جرم‌گیری و پاکسازی"},
            ),
            (
                "پوسدگی",
                "ترمیم دندان",
                {"ترمیم دندان", "معاینه اولیه دندانپزشکی"},
            ),
        )
        for query, first, expected in cases:
            with self.subTest(query=query):
                names = await self._names(query)
                self.assertEqual(names[0], first)
                self.assertTrue(expected.issubset(set(names)))
                self.assertNotIn("بلیچینگ", names)

    async def test_multiword_and_word_suffix_variants_stay_relevant(self):
        names = await self._names("درد و پوسیدگی دندان‌هام")
        self.assertEqual(
            names[:2],
            ["معاینه اولیه دندانپزشکی", "ترمیم دندان"],
        )
        self.assertNotIn("جرم‌گیری و پاکسازی", names)
        self.assertNotIn("بلیچینگ", names)

    async def test_spelling_typo_does_not_fall_back_to_unrelated_services(self):
        names = await self._names("پوسدگی دندن")
        self.assertEqual(names[0], "ترمیم دندان")
        self.assertNotIn("جرم‌گیری و پاکسازی", names)
        self.assertNotIn("بلیچینگ", names)
        self.assertEqual(await self._names("بیمه"), [])


if __name__ == "__main__":
    unittest.main()
