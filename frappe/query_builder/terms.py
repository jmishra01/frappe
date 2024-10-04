import re
from datetime import datetime, time, timedelta
from typing import Any

from pypika.queries import QueryBuilder
from pypika.terms import Array, Criterion, Function, Node, NodeT, NullValue, Term, Tuple, ValueWrapper
from pypika.utils import format_alias_sql

import frappe
from frappe.utils.data import format_time, format_timedelta


class NamedParameterWrapper:
	"""Utility class to hold parameter values and keys"""

	def __init__(self) -> None:
		self.parameters = {}

	def get_sql(self, param_value: Any, **kwargs) -> str:
		"""returns SQL for a parameter, while adding the real value in a dict

		Args:
		                param_value (Any): Value of the parameter

		Returns:
		                str: parameter used in the SQL query
		"""
		param_key = f"%(param{len(self.parameters) + 1})s"
		self.parameters[param_key[2:-2]] = param_value
		return param_key

	def get_parameters(self) -> dict[str, Any]:
		"""get dict with parameters and values

		Returns:
		                Dict[str, Any]: parameter dict
		"""
		return self.parameters


class ParameterizedValueWrapper(ValueWrapper):
	"""
	Class to monkey patch ValueWrapper

	Adds functionality to parameterize queries when a `param wrapper` is passed in get_sql()
	"""

	def get_sql(
		self,
		quote_char: str | None = None,
		secondary_quote_char: str = "'",
		param_wrapper: NamedParameterWrapper | None = None,
		**kwargs: Any,
	) -> str:
		if param_wrapper and isinstance(self.value, str):
			if self.value.startswith('to_timestamp'):
				sql = self.value
			else:
				# add quotes if it's a string value
				value_sql = self.get_value_sql(quote_char=quote_char, **kwargs)
				sql = param_wrapper.get_sql(param_value=value_sql, **kwargs)
		elif isinstance(self.value, str) and (self.value.startswith('to_timestamp') or self.value.startswith('to_date')):
			sql = self.value
		else:
			# * BUG: pypika doesen't parse timedeltas and datetime.time
			if isinstance(self.value, timedelta):
				self.value = format_timedelta(self.value)
				if frappe.is_oracledb:
					print(f"VALUE: {self.value}")
					return f"to_timestamp('{self.value}', 'yyyy-mm-dd hh24:mi:ss.ff6')"
			elif isinstance(self.value, time):
				self.value = format_time(self.value)
				if frappe.is_oracledb:
					print(f"VALUE: {self.value}")
					return f"to_timestamp('{self.value}', 'yyyy-mm-dd hh24:mi:ss.ff6')"
			elif isinstance(self.value, datetime):
				self.value = frappe.db.format_datetime(self.value)
				if frappe.is_oracledb:
					print(f"VALUE: {self.value}")
					return f"to_timestamp('{self.value}', 'yyyy-mm-dd hh24:mi:ss.ff6')"
			elif frappe.is_oracledb:
				self.value = conversion_column_value(self.value)
				return self.value


			sql = self.get_value_sql(
				quote_char=quote_char,
				secondary_quote_char=secondary_quote_char,
				param_wrapper=param_wrapper,
				**kwargs,
			)
		return format_alias_sql(sql, self.alias, quote_char=quote_char, **kwargs)


class ParameterizedFunction(Function):
	"""
	Class to monkey patch pypika.terms.Functions

	Only to pass `param_wrapper` in `get_function_sql`.
	"""

	def get_sql(self, **kwargs: Any) -> str:
		with_alias = kwargs.pop("with_alias", False)
		with_namespace = kwargs.pop("with_namespace", False)
		quote_char = kwargs.pop("quote_char", None)
		dialect = kwargs.pop("dialect", None)
		param_wrapper = kwargs.pop("param_wrapper", None)

		function_sql = self.get_function_sql(
			with_namespace=with_namespace,
			quote_char=quote_char,
			param_wrapper=param_wrapper,
			dialect=dialect,
		)

		if self.schema is not None:
			function_sql = "{schema}.{function}".format(
				schema=self.schema.get_sql(quote_char=quote_char, dialect=dialect, **kwargs),
				function=function_sql,
			)

		if with_alias:
			return format_alias_sql(function_sql, self.alias, quote_char=quote_char, **kwargs)

		return function_sql


def conversion_column_value(value: str | int, convert_to_date: bool = True):
	if isinstance(value, str):
		if not value:
			return "''"

		if value[0] == "'" and value[-1] == "'":
			value = value[1:-1]

		if convert_to_date and re.search('^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}\.\d+$', value):  # noqa: W605
			ret = f"to_timestamp('{value}', 'yyyy-mm-dd hh24:mi:ss.ff6')"
		elif convert_to_date and re.search('^\d{4}-\d{2}-\d{2} \d{2}:\d{2}:\d{2}$', value):  # noqa: W605
			ret = f"to_timestamp('{value}', 'yyyy-mm-dd hh24:mi:ss')"
		elif convert_to_date and re.search('^\d{4}-\d{2}-\d{2}$', value):  # noqa: W605
			ret = f"to_date('{value}', 'yyyy-mm-dd')"
		elif value[0] != "'" or value[-1] != "'":
			ret = "'{}'".format(value.replace("'", "''"))
		else:
			ret = value
	elif value is None:
		ret = 'NULL'
	else:
		ret = str(value)

	return ret



class SubQuery(Criterion):
	def __init__(
		self,
		subq: QueryBuilder,
		alias: str | None = None,
	) -> None:
		super().__init__(alias)
		self.subq = subq

	def get_sql(self, **kwg: Any) -> str:
		kwg["subquery"] = True
		return self.subq.get_sql(**kwg)

subqry = SubQuery
