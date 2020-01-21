from tesserae.db.entities import Feature
from tesserae.tokenizers import GreekTokenizer, LatinTokenizer
from tesserae.unitizer import Unitizer
from tesserae.utils import TessFile


_tokenizers = {
    'greek': GreekTokenizer,
    'latin': LatinTokenizer,
}


def ingest_text(connection, text):
    """Update database with a new text

    ``text`` must not already exist in the database

    Parameters
    ----------
    connection : tesserae.db.TessMongoConnection
        A connection to the database
    text : tesserae.db.entities.Text
        The text to be ingested

    Returns
    -------
    ObjectId
        database identifier for the Text object just added

    Raises
    ------
    ValueError
        Raised when unknown language is encountered
    """
    if text.language not in _tokenizers:
        raise ValueError('Unknown language: {}'.format(text.language))
    tessfile = TessFile(text.path, metadata=text)

    result = connection.insert(text)
    text_id = result.inserted_ids[0]

    tokens, tags, features = \
        _tokenizers[tessfile.metadata.language](connection).tokenize(
            tessfile.read(), text=tessfile.metadata)

    feature_cache = {(f.feature, f.token): f for f in connection.find(
        Feature.collection, language=text.language)}
    features_for_insert = []
    features_for_update = []

    for f in features:
        if (f.feature, f.token) not in feature_cache:
            features_for_insert.append(f)
            feature_cache[(f.feature, f.token)] = f
        else:
            f.id = feature_cache[(f.feature, f.token)].id
            features_for_update.append(f)
    insert_features_result = connection.insert(features_for_insert)
    update_features_result = connection.update(features_for_update)

    unitizer = Unitizer()
    lines, phrases = unitizer.unitize(tokens, tags, tessfile.metadata)

    result = connection.insert_nocheck(tokens)
    result = connection.insert_nocheck(lines + phrases)

    return text_id
