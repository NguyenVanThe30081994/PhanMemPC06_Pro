# -*- coding: utf-8 -*-
import os
import unittest
from unittest.mock import patch

from storage import _normalize_database_uri, _resolve_database_uri


class StorageTests(unittest.TestCase):
    def test_normalize_database_uri_promotes_mysql_driver(self):
        self.assertEqual(
            _normalize_database_uri("mysql://user:pass@host/dbname"),
            "mysql+pymysql://user:pass@host/dbname",
        )
        self.assertEqual(
            _normalize_database_uri("mariadb://user:pass@host/dbname"),
            "mariadb+pymysql://user:pass@host/dbname",
        )

    def test_resolve_database_uri_requires_external_db_under_passenger(self):
        env = {
            "PASSENGER_APP_ENV": "production",
        }
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                _resolve_database_uri("/tmp/app", "/tmp/data")

        env["DATABASE_URL"] = "sqlite:///pc06_system.db"
        with patch.dict(os.environ, env, clear=False):
            with self.assertRaises(RuntimeError):
                _resolve_database_uri("/tmp/app", "/tmp/data")

        env["DATABASE_URL"] = "mysql://user:pass@host/dbname"
        with patch.dict(os.environ, env, clear=False):
            self.assertEqual(
                _resolve_database_uri("/tmp/app", "/tmp/data"),
                "mysql+pymysql://user:pass@host/dbname",
            )


if __name__ == "__main__":
    unittest.main()
