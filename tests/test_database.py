from unittest.mock import patch

import pytest
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from database import Base, Product, _migrate_db, get_db, init_db


@pytest.fixture
def mem_engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    yield engine
    Base.metadata.drop_all(bind=engine)


class TestGetDb:
    def test_yields_a_usable_session(self, mem_engine):
        with patch("database.engine", mem_engine):
            gen = get_db()
            session = next(gen)
            assert session is not None
            assert isinstance(session, Session)
            try:
                next(gen)
            except StopIteration:
                pass


class TestMigrateDb:
    def test_noop_when_all_columns_present(self, mem_engine):
        with patch("database.engine", mem_engine):
            _migrate_db()  # should not raise
        cols = {c["name"] for c in inspect(mem_engine).get_columns("price_checks")}
        assert "in_stock" in cols

    def test_adds_in_stock_column_when_missing(self, mem_engine):
        with mem_engine.connect() as conn:
            conn.execute(text("ALTER TABLE price_checks DROP COLUMN in_stock"))
            conn.commit()

        cols_before = {c["name"] for c in inspect(mem_engine).get_columns("price_checks")}
        assert "in_stock" not in cols_before

        with patch("database.engine", mem_engine):
            _migrate_db()

        cols_after = {c["name"] for c in inspect(mem_engine).get_columns("price_checks")}
        assert "in_stock" in cols_after

    def test_adds_site_column_when_missing(self, mem_engine):
        with mem_engine.connect() as conn:
            conn.execute(text("ALTER TABLE products DROP COLUMN site"))
            conn.commit()

        cols_before = {c["name"] for c in inspect(mem_engine).get_columns("products")}
        assert "site" not in cols_before

        with patch("database.engine", mem_engine):
            _migrate_db()

        cols_after = {c["name"] for c in inspect(mem_engine).get_columns("products")}
        assert "site" in cols_after


class TestInitDb:
    def test_creates_all_tables(self, mem_engine):
        Base.metadata.drop_all(bind=mem_engine)
        tables_before = inspect(mem_engine).get_table_names()
        assert "products" not in tables_before

        with patch("database.engine", mem_engine):
            init_db()

        tables_after = inspect(mem_engine).get_table_names()
        assert "products" in tables_after
        assert "variants" in tables_after
        assert "price_checks" in tables_after
