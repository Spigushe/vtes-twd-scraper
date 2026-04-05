"""Tests for vtes_scraper._krcg_helper module.

Strategy: mock the krcg module in sys.modules so tests never touch the
real VTES database, keeping them fast and deterministic.
"""

import sys
import types
from unittest.mock import MagicMock, patch

import vtes_scraper._krcg_helper as kh

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_state() -> None:
    """Restore module-level cache to its initial (unchecked) state."""
    kh._krcg_loaded = None
    kh._seen_cards.clear()
    kh._cards_loaded.clear()


def _make_krcg_mock(get_return_value=None):
    """Return a (mock_krcg_module, mock_vtes_module) pair.

    mock_krcg.vtes.VTES.get returns *get_return_value*.
    mock_krcg.vtes.VTES.load is a no-op.
    """
    mock_vtes_mod = MagicMock()
    mock_vtes_mod.VTES.get.return_value = get_return_value
    mock_krcg_mod = MagicMock()
    mock_krcg_mod.vtes = mock_vtes_mod
    return mock_krcg_mod, mock_vtes_mod


def _make_crypt_card(
    *,
    card_id: int = 1001,
    crypt: bool = True,
    adv: bool = False,
    group: object = "6",
    capacity: int = 4,
    disciplines: list[str] | None = None,
    clans: list[str] | None = None,
    title: str | None = None,
    variants: dict | None = None,
) -> MagicMock:
    card = MagicMock()
    card.id = card_id
    card.crypt = crypt
    card.adv = adv
    card.group = group
    card.capacity = capacity
    card.disciplines = ["PRO", "ani"] if disciplines is None else disciplines
    card.clans = ["Gangrel"] if clans is None else clans
    card.title = title
    card.variants = {} if variants is None else variants
    return card


# ---------------------------------------------------------------------------
# _is_krcg_loaded
# ---------------------------------------------------------------------------


class TestIsKrcgLoaded:
    def setup_method(self):
        _reset_state()

    def teardown_method(self):
        _reset_state()

    def test_returns_cached_true(self):
        kh._krcg_loaded = True
        assert kh._is_krcg_loaded() is True

    def test_returns_cached_false(self):
        kh._krcg_loaded = False
        assert kh._is_krcg_loaded() is False

    def test_loads_and_caches_true(self):
        mock_krcg, _ = _make_krcg_mock()
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh._is_krcg_loaded()
        assert result is True
        assert kh._krcg_loaded is True

    def test_import_error_caches_false(self):
        """When krcg.vtes cannot be imported, _is_krcg_loaded returns False."""
        broken = types.ModuleType("krcg")
        # broken has no 'vtes' attribute → 'from krcg import vtes' raises ImportError
        saved_vtes = sys.modules.pop("krcg.vtes", None)
        try:
            with patch.dict(sys.modules, {"krcg": broken}):
                result = kh._is_krcg_loaded()
        finally:
            if saved_vtes is not None:
                sys.modules["krcg.vtes"] = saved_vtes
        assert result is False
        assert kh._krcg_loaded is False


# ---------------------------------------------------------------------------
# _krcg_card_search
# ---------------------------------------------------------------------------


class TestKrcgCardSearch:
    def setup_method(self):
        _reset_state()

    def teardown_method(self):
        _reset_state()

    def test_returns_none_when_krcg_not_loaded(self):
        kh._krcg_loaded = False
        assert kh._krcg_card_search("Blood Doll") is None

    def test_returns_cached_result(self):
        mock_card = MagicMock()
        kh._krcg_loaded = True
        kh._seen_cards.add("Blood Doll")
        kh._cards_loaded["Blood Doll"] = mock_card
        assert kh._krcg_card_search("Blood Doll") is mock_card

    def test_returns_none_from_cache_when_card_missing(self):
        """Cache hit that stored None still returns None."""
        kh._krcg_loaded = True
        kh._seen_cards.add("Unknown")
        kh._cards_loaded["Unknown"] = None
        assert kh._krcg_card_search("Unknown") is None

    def test_fetches_card_from_database(self):
        mock_card = MagicMock()
        mock_krcg, _ = _make_krcg_mock(get_return_value=mock_card)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh._krcg_card_search("Blood Doll")
        assert result is mock_card
        assert "Blood Doll" in kh._seen_cards
        assert kh._cards_loaded["Blood Doll"] is mock_card

    def test_logs_when_card_not_in_database(self):
        mock_krcg, _ = _make_krcg_mock(get_return_value=None)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh._krcg_card_search("Nonexistent Card")
        assert result is None
        assert "Nonexistent Card" in kh._seen_cards

    def test_fetches_card_by_integer_id(self):
        mock_card = MagicMock()
        mock_krcg, _ = _make_krcg_mock(get_return_value=mock_card)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh._krcg_card_search(1001)
        assert result is mock_card
        assert 1001 in kh._seen_cards


# ---------------------------------------------------------------------------
# get_all_vamp_variants
# ---------------------------------------------------------------------------


class TestGetAllVampVariants:
    def setup_method(self):
        _reset_state()

    def teardown_method(self):
        _reset_state()

    def test_returns_empty_when_krcg_not_loaded(self):
        kh._krcg_loaded = False
        assert kh.get_all_vamp_variants("Xaviar") == []

    def test_returns_empty_when_not_a_crypt_card(self):
        mock_card = _make_crypt_card(crypt=False)
        mock_krcg, _ = _make_krcg_mock(get_return_value=mock_card)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Blood Doll")
        assert result == []

    def test_returns_variant_data_for_non_adv(self):
        mock_card = _make_crypt_card()
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_card)
        # Also make integer-id lookups return the same card
        mock_vtes.VTES.get.return_value = mock_card
        kh._krcg_loaded = True
        kh._seen_cards.add(1001)
        kh._cards_loaded[1001] = mock_card
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert len(result) == 1
        entry = result[0]
        assert "capacity" in entry and entry["capacity"] == 4
        assert "disciplines" in entry and "PRO" in entry["disciplines"]
        assert "clan" in entry and entry["clan"] == "Gangrel"
        assert "grouping" in entry and entry["grouping"] == 6

    def test_skips_adv_when_looking_up_base(self):
        mock_adv = _make_crypt_card(adv=True)
        mock_base = _make_crypt_card(adv=False, card_id=1002, variants={})
        # Search by name returns the base card which has an ADV variant
        mock_base.variants = {"adv": 1003}
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_base)

        def _side_effect(card_id, default=None):
            if card_id == "Nathan Turner":
                return mock_base
            if card_id == 1002:
                return mock_base
            if card_id == 1003:
                return mock_adv
            return default

        mock_vtes.VTES.get.side_effect = _side_effect
        kh._krcg_loaded = True
        kh._seen_cards.update([1002, 1003])
        kh._cards_loaded[1002] = mock_base
        kh._cards_loaded[1003] = mock_adv

        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Nathan Turner")

        # Only non-ADV variants should be returned
        assert all(not r.get("adv") for r in result)

    def test_handles_group_any(self):
        mock_card = _make_crypt_card(group="ANY")
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_card)
        mock_vtes.VTES.get.return_value = mock_card
        kh._krcg_loaded = True
        kh._seen_cards.add(1001)
        kh._cards_loaded[1001] = mock_card
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Generic Vampire")
        assert "grouping" in result[0] and result[0]["grouping"] == "ANY"

    def test_skips_cards_with_no_group(self):
        mock_card = _make_crypt_card(group="")
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_card)
        mock_vtes.VTES.get.return_value = mock_card
        kh._krcg_loaded = True
        kh._seen_cards.add(1001)
        kh._cards_loaded[1001] = mock_card
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("No Group Vamp")
        assert result == []

    def test_skips_variant_with_no_disciplines(self):
        mock_card = _make_crypt_card(disciplines=[])
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_card)
        mock_vtes.VTES.get.return_value = mock_card
        kh._krcg_loaded = True
        kh._seen_cards.add(1001)
        kh._cards_loaded[1001] = mock_card
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert "disciplines" in result[0] and result[0]["disciplines"] == ""

    def test_card_with_no_clan(self):
        mock_card = _make_crypt_card(clans=[])
        mock_krcg, mock_vtes = _make_krcg_mock(get_return_value=mock_card)
        mock_vtes.VTES.get.return_value = mock_card
        kh._krcg_loaded = True
        kh._seen_cards.add(1001)
        kh._cards_loaded[1001] = mock_card
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_all_vamp_variants("Clanless")
        assert "clan" in result[0] and result[0]["clan"] == ""

    def test_variant_key_error_is_skipped(self):
        """KeyError from _krcg_card_search for a variant id is caught and skipped."""
        main_card = _make_crypt_card(card_id=1001, variants={1: 2001})

        def _mock_search(key):
            if key in ("Nathan Turner", 1001):
                return main_card
            raise KeyError(key)

        kh._krcg_loaded = True
        with patch.object(kh, "_krcg_card_search", side_effect=_mock_search):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert len(result) == 1  # 2001 skipped via KeyError

    def test_variant_returns_none_is_skipped(self):
        """None from _krcg_card_search for a variant id is skipped."""
        main_card = _make_crypt_card(card_id=1001, variants={1: 2001})

        def _mock_search(key):
            if key in ("Nathan Turner", 1001):
                return main_card
            return None

        kh._krcg_loaded = True
        with patch.object(kh, "_krcg_card_search", side_effect=_mock_search):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert len(result) == 1  # 2001 skipped (None)

    def test_variant_non_crypt_is_skipped(self):
        """Variant with crypt=False is skipped."""
        lib_card = _make_crypt_card(card_id=2001, crypt=False)
        main_card = _make_crypt_card(card_id=1001, variants={1: 2001})

        def _mock_search(key):
            if key in ("Nathan Turner", 1001):
                return main_card
            return lib_card

        kh._krcg_loaded = True
        with patch.object(kh, "_krcg_card_search", side_effect=_mock_search):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert len(result) == 1  # lib_card skipped (not crypt)

    def test_variant_bad_group_type_is_skipped(self):
        """TypeError from int(raw_group) is caught and the variant is skipped."""
        bad_card = _make_crypt_card(card_id=2001, group=[1, 2])  # list → int() raises TypeError
        main_card = _make_crypt_card(card_id=1001, variants={1: 2001})

        def _mock_search(key):
            if key in ("Nathan Turner", 1001):
                return main_card
            return bad_card

        kh._krcg_loaded = True
        with patch.object(kh, "_krcg_card_search", side_effect=_mock_search):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert len(result) == 1  # bad_card skipped (group not int-convertible)

    def test_outer_exception_returns_empty_list(self):
        """Unexpected exception in the outer try block returns []."""
        main_card = _make_crypt_card(card_id=1001, variants={})

        def _mock_search(key):
            if key == "Nathan Turner":
                return main_card
            raise RuntimeError("unexpected!")  # propagates to outer except

        kh._krcg_loaded = True
        with patch.object(kh, "_krcg_card_search", side_effect=_mock_search):
            result = kh.get_all_vamp_variants("Nathan Turner")
        assert result == []


# ---------------------------------------------------------------------------
# get_library_card_type
# ---------------------------------------------------------------------------


class TestGetLibraryCardType:
    def setup_method(self):
        _reset_state()

    def teardown_method(self):
        _reset_state()

    def test_returns_none_when_krcg_not_loaded(self):
        kh._krcg_loaded = False
        assert kh.get_library_card_type("Blood Doll") is None

    def test_returns_none_when_card_not_found(self):
        mock_krcg, _ = _make_krcg_mock(get_return_value=None)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_library_card_type("Nonexistent")
        assert result is None

    def test_returns_single_type(self):
        mock_card = MagicMock()
        mock_card.types = ["Master"]
        mock_krcg, _ = _make_krcg_mock(get_return_value=mock_card)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_library_card_type("Blood Doll")
        assert result == "Master"

    def test_returns_sorted_joined_types(self):
        mock_card = MagicMock()
        mock_card.types = ["Combat", "Action"]
        mock_krcg, _ = _make_krcg_mock(get_return_value=mock_card)
        kh._krcg_loaded = True
        with patch.dict(sys.modules, {"krcg": mock_krcg}):
            result = kh.get_library_card_type("Multi-type Card")
        assert result == "Action/Combat"
