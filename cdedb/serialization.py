#!/usr/bin/env python3

"""We use :py:mod:`Pyro4` for RPC and with it the default serializer
:py:mod:`serpent`, which basically converts every more complex type into
a string. For enhanced comfort we define some custom extensions for data
types we actually use.

We wrap the values of interest into a :py:class:`dict`, which is not
hashable. Thus our custom serializers may not operate on
:py:class:`dict` keys or :py:class:`set` elements. If this happens, a
:py:exc:`TypeError` is raised upon deserialization.
"""

import datetime
import dateutil.parser
import collections.abc
import decimal

#: Skeleton for custom serialization wrapper. :py:attr:`_class` and
#: :py:attr:`_value` have to be filled in accordingly.
_BASE_DICT = {
    "_CDEDB_CUSTOM_SERIALIZATION" : True,
    "_class" : None,
    "_value" : None,
}

def _date_serializer(obj, serpent_serializer, out, level):
    """Serialize datetime.date and datetime.datetime.

    Unfortunately ``isinstance(datetime.datetime.now(), datetime.date) ==
    True``, hence we need to handle datetime.datetime here as well.
    """
    ret = _BASE_DICT.copy()
    if isinstance(obj, datetime.datetime):
        ret["_class"] = "datetime.datetime"
    else:
        ret["_class"] = "datetime.date"
    ret["_value"] = obj.isoformat()
    serpent_serializer._serialize(ret, out, level)

def _isoformat_serializer_generator(classname):
    """Serialize objects which provide a ``.isoformat()`` method for this
    purpose.

    :type classname: str
    :rtype: callable
    """
    def _isoformat_serializer(obj, serpent_serializer, out, level):
        ret = _BASE_DICT.copy()
        ret["_class"] = classname
        ret["_value"] = obj.isoformat()
        serpent_serializer._serialize(ret, out, level)
    return _isoformat_serializer

def _date_deserializer(obj):
    return dateutil.parser.parse(obj, dayfirst=True).date()

def _datetime_deserializer(obj):
    return dateutil.parser.parse(obj, dayfirst=True)

def _time_deserializer(obj):
    return dateutil.parser.parse(obj, dayfirst=True).time()

def _trivial_serializer_generator(classname):
    """Serialize by calling :py:func:`str` on the object.

    :type classname: str
    :rtype: callable
    """
    def _trivial_serializer(obj, serpent_serializer, out, level):
        ret = _BASE_DICT.copy()
        ret["_class"] = classname
        ret["_value"] = str(obj)
        serpent_serializer._serialize(ret, out, level)
    return _trivial_serializer

def _trivial_deserializer_generator(atype):
    """Deserialize by calling the construnctor with the serialized string
    representation.

    :type atype: type
    :rtype: atype
    """
    def _trivial_deserializer(obj):
        return atype(obj)
    return _trivial_deserializer

#: The custom serializers have to conform to the interface needed by
#: serpent.
SERIALIZERS = {
    datetime.date : _date_serializer,
    datetime.time : _isoformat_serializer_generator("datetime.time"),
    float : _trivial_serializer_generator("float"),
    decimal.Decimal : _trivial_serializer_generator("decimal.Decimal"),
}

#: The custom deserializers are called with one :py:class:`str` argument.
_DESERIALIZERS = {
    "datetime.date" : _date_deserializer,
    "datetime.datetime" : _datetime_deserializer,
    "datetime.time" : _time_deserializer,
    "float" : _trivial_deserializer_generator(float),
    "decimal.Decimal" : _trivial_deserializer_generator(decimal.Decimal),
}

def deserialize(obj):
    """Invert our custom serialization. The input has allready been
    deserialized by serpent.

    :type obj: str
    :rtype: object
    """
    if isinstance(obj, collections.abc.Sequence):
        if isinstance(obj, (str, bytes, bytearray)):
            return obj
        else:
            return tuple(deserialize(x) for x in obj)
    elif isinstance(obj, collections.abc.Set):
        return set(deserialize(x) for x in obj)
    elif isinstance(obj, collections.abc.Mapping):
        if obj.get("_CDEDB_CUSTOM_SERIALIZATION", False):
            return _DESERIALIZERS[obj['_class']](obj['_value'])
        else:
            return {key : deserialize(value) for key, value in obj.items()}
    else:
        return obj
