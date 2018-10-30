"""Database standardization for text units.

Classes
-------
Unit
    Text unit data model with token indices.
"""
import typing

from bson.objectid import ObjectId

from tesserae.db.entities.entity import Entity
from tesserae.db.entities.token import Token


class Unit(Entity):
    """Group of words that make up a set to match on.

    Units are the chunks of text that matches are computed on. Units can
    come in the flavor of lines in a poem, sentences, paragraphs, etc.

    Parameters
    ----------
    id : bson.ObjectId, optional
        Database id of the text. Should not be set locally.
    text : str, optional
        The text that contains this unit.
    index : int, optional
        The order of this unit in the text. This is relative to Units of a
        particular type.
    unit_type : str, optional
        How the chunk of text in this Unit was defined, e.g., "line",
        "phrase", etc.
    tokens : list of tesserae.db.Token or bson.objectid.ObjectId, optional
        The tokens that make up this unit.

    Attributes
    ----------
    id : bson.ObjectId
        Database id of the text. Should not be set locally.
    text : str
        The text that contains this unit.
    index : int
        The order of this unit in the text. This is relative to Units of a
        particular type.
    unit_type : str
        How the chunk of text in this Unit was defined, e.g., "line",
        "phrase", etc.
    tokens : list of tesserae.db.Token or bson.objectid.ObjectId
        The tokens that make up this unit.

    """

    collection = 'units'

    def __init__(self, id=None, text=None, index=None, unit_type=None,
                 tokens=None):
        super(Unit, self).__init__(id=id)
        self.text: typing.Optional[str] = text
        self.index: typing.Optional[int] = index
        self.unit_type: typing.Optional[str] = unit_type
        self.tokens: typing.List[typing.Union[str, ObjectId, Token]] = \
            tokens if tokens is not None else []