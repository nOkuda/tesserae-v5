"""Functionality related to multitext search"""
from collections import defaultdict
import itertools
import os
import sqlite3
import time

from bson.objectid import ObjectId
import numpy as np

from tesserae.db.entities import \
    Feature, Match, MultiResult, Search, Text, Unit
from tesserae.utils.calculations import get_text_frequencies


MULTITEXT_SEARCH = 'multitext'


def submit_multitext(jobqueue, results_id, search_id_str, texts_ids_strs):
    """Submit a job for multitext search

    Multitext search submitted by this function will always return results
    based on phrases

    Parameters
    ----------
    jobqueue : tesserae.utils.coordinate.JobQueue
    results_id : str
        UUID to associate with the multitext search to be performed
    search_id_str : str
        stringified ObjectId of the Search results on which to run multitext
        search
    texts_ids_str : list of str
        stringified ObjectIds of Texts in which bigrams of the Search results
        are to be searched

    """
    kwargs = {
        'results_id': results_id,
        'search_id_str': search_id_str,
        'texts_ids_strs': texts_ids_strs
    }
    jobqueue.queue_job(_run_multitext, kwargs)


def _run_multitext(connection, results_id, search_id_str, texts_ids_strs):
    """Runs multitext search

    Parameters
    ----------
    connection : tesserae.db.TessMongoConnection
    results_id : str
        UUID to associate with the multitext search to be performed
    search_id_str : str
        stringified ObjectId of the Search results on which to run multitext
        search
    texts_ids_str : list of str
        stringified ObjectIds of Texts in which bigrams of the Search results
        are to be searched

    """
    start_time = time.time()
    parameters = {
        'search_id': search_id_str,
        'text_ids': texts_ids_str
    }
    results_status = Search(
        results_id=results_id,
        search_type=MULTITEXT_SEARCH,
        status=Search.INIT, msg='',
        parameters=parameters
    )
    connection.insert(results_status)
    search_id = ObjectId(search_id_str)
    search = connection.find(Search.collection, _id=search_id)
    matches = connection.find(
        Match.collection, search_id=search_id)
    texts = connection.find(
        Text.collection, _id=[ObjectId(tid) for tid in texts_ids]
    )
    try:
        search_id = results_status.id
        results_status.status = Search.RUN
        connection.update(results_status)
        raw_results = multitext_search(
            connection, matches, search.parameters['method']['feature'],
            'phrase', texts)
        multiresults = [MultiResult(
            search_id=search_id,
            match_id=m.id,
            bigram=list(bigram),
            units=[v[0] for v in values],
            scores=[v[1] for v in values]
        ) for m, result in zip(matches, raw_results)
                        for bigram, values in result.items()]
        connection.insert_nocheck(multiresults)

        results_status.status = Search.DONE
        results_status.msg = 'Done in {} seconds'.format(
            time.time() - start_time)
        connection.update(results_status)
    # we want to catch all errors and log them into the Search entity
    except:  # noqa: E722
        results_status.status = Search.FAILED
        results_status.msg = traceback.format_exc()
        connection.update(results_status)


def compute_tesserae_score(inverse_frequencies, distances):
    """Compute Tesserae score

    Parameters
    ----------
    inverse_frequencies : list of float
    distances : list of int

    Returns
    -------
    float

    """
    return np.log(sum(inverse_frequencies) / sum(distances))


def compute_inverse_frequencies(connection, feature_type, text_id):
    """Compute inverse text frequencies by specified feature type

    Parameters
    ----------
    connection : tesserae.db.mongodb.TessMongoConnection
    feature_type : str
        Feature category to be used in calculating frequencies
    text_id : bson.objectid.ObjectId
        ObjectId of the text whose feature frequencies are to be computed

    Returns
    -------
    1d np.array
        index by form index to obtain corresponding inverse text frequency
    """
    text_freqs_dict = get_text_frequencies(
        connection, feature_type, text_id)
    inverse_frequencies = np.zeros(max(text_freqs_dict) + 1)
    inverse_frequencies[[k for k in text_freqs_dict.keys()]] = np.power([
        v for v in text_freqs_dict.values()
    ], -1)
    return inverse_frequencies


class BigramWriter:
    """Handles writing bigram databases

    Intended to be used in a context (via "with").  Can register bigram data to
    be written to a database.

    Upon closing, a BigramWriter, will flush all remaining data and build
    indices on the databases.
    """

    BIGRAM_DB_DIR = os.path.join(
        os.path.expanduser('~'), 'tess_data', 'bigrams')
    transaction_threshold = 10000

    def __init__(self, text_id, unit_type):
        """

        As a side-effect, the bigram database directory is created if it does
        not already exist

        Parameters
        ----------
        text_id : ObjectId
            ObjectId of Text
        unit_type : {'line', 'phrase'}
            the type of Unit in which the bigrams are found
        """
        if not os.path.isdir(BigramWriter.BIGRAM_DB_DIR):
            os.makedirs(BigramWriter.BIGRAM_DB_DIR, exist_ok=True)
        self.text_id = text_id
        self.unit_type = unit_type
        # dict[feature, list[db_row]]
        self.data = defaultdict(list)

    def record_bigrams(self, feature, positioned_unigrams, forms,
                       inverse_frequencies, unit_id):
        """Compute and store bigram information

        It is assumed that all of the Unit's unigram information for the
        specified feature are passed in

        When enough bigrams have been collected, this BigramWriter will write
        out the data to the appropriate database

        Parameters
        ----------
        feature : str
            the type of feature being recorded
        positioned_unigrams : list of list of int
            the outer list corresponds to a position within the Unit; the inner
            list contains the individual instances of the feature type
        forms : list of list of int
            the outer list corresponds to a position within the Unit; the inner
            list contains the individual instances of the form feature type
        inverse_frequencies : 1d np.array
            mapping from form index number to text frequency for text to which
            the unit associated with ``unit_id`` belongs
        unit_id : ObjectId
            ObjectId of the Unit whose bigrams are being recorded
        """
        collected = {}
        for pos1, (unigrams1, outerform1) in enumerate(
                zip(positioned_unigrams, forms)):
            form1 = outerform1[0]
            for word1 in unigrams1:
                pos2_start = pos1 + 1
                for pos2_increment, (unigrams2, outerform2) in enumerate(
                        zip(positioned_unigrams[pos2_start:],
                            forms[pos2_start:])):
                    form2 = outerform2[0]
                    for word2 in unigrams2:
                        bigram = tuple(sorted([word1, word2]))
                        if bigram not in collected:
                            collected[bigram] = compute_tesserae_score(
                                inverse_frequencies[[form1, form2]],
                                # distances are computed as expected in
                                # multitext (i.e., two adjacent words have a
                                # distance of 1, words that have one word
                                # between them have a distance of two, etc.)
                                (pos2_increment + 1,))
        unit_id_binary = unit_id.binary
        to_write = self.data[feature]
        to_write.extend([
            (word1, word2, unit_id_binary, score)
            for (word1, word2), score in collected.items()
        ])

        if len(to_write) > BigramWriter.transaction_threshold:
            self.write_data(feature, to_write)
            to_write.clear()

    def write_data(self, feature, to_write):
        """Write out bigram information to database

        Parameters
        ----------
        feature : str
            the type of feature being recorded
        to_write : list 5-tuple
        """
        dbpath = _create_bigram_db_path(
            self.text_id, self.unit_type, feature)
        if not os.path.exists(dbpath):
            conn = sqlite3.connect(dbpath)
            conn.execute('create table bigrams('
                            'id integer primary key, '
                            'word1 integer, '
                            'word2 integer, '
                            'unitid blob(12), '
                            'score real '
                         ')')
        else:
            conn = sqlite3.connect(dbpath)
        with conn:
            conn.executemany(
                'insert into bigrams(word1, word2, unitid, score) '
                'values (?, ?, ?, ?)',
                to_write
            )
        conn.close()

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        for feature, to_write in self.data.items():
            if to_write:
                self.write_data(feature, to_write)
                to_write.clear()
            dbpath = _create_bigram_db_path(
                self.text_id, self.unit_type, feature)
            conn = sqlite3.connect(dbpath)
            conn.execute('drop index if exists bigrams_index')
            conn.execute('create index bigrams_index on bigrams ('
                         'word1, word2)')


def _create_bigram_db_path(text_id, unit_type, feature):
    """Create a path to the bigram database for the specified options

    Parameters
    ----------
    text_id : ObjectId
        ObjectId of Text
    unit_type : {'line', 'phrase'}
        the type of Unit in which the bigrams are found
    feature : str
        the type of feature of the bigrams

    Returns
    -------
    str
        the path of the bigram database associated with the specified options

    """
    text_id_str = str(text_id)
    return str(os.path.join(
        BigramWriter.BIGRAM_DB_DIR, f'{text_id_str}_{unit_type}_{feature}.db'))


def register_bigrams(connection, text_id):
    """Compute and store bigram information for the specified Text

    Parameters
    ----------
    connection : tesserae.db.TessMongoConnection
        A connection to the Tesserae database
    text_id : ObjectId
        ObjectId of Text

    """
    accepted_features = ('form', 'lemmata')
    feat2inv_freqs = {
        f_type: compute_inverse_frequencies(connection, f_type, text_id)
        for f_type in accepted_features
    }
    for unit_type in ['line', 'phrase']:
        with connection.connection[Unit.collection].find(
            {'text': text_id, 'unit_type': unit_type},
            {'_id': True, 'tokens': True},
            no_cursor_timeout=True
        ) as unit_cursor:
            with BigramWriter(text_id, unit_type) as writer:
                for unit_dict in unit_cursor:
                    by_feature = defaultdict(list)
                    unit_id = unit_dict['_id']
                    tokens = unit_dict['tokens']
                    for t in tokens:
                        for feature, values in t['features'].items():
                            if feature in accepted_features:
                                by_feature[feature].append(values)
                    for feature, values in by_feature.items():
                        writer.record_bigrams(
                            feature, values, by_feature['form'],
                            feat2inv_freqs[feature], unit_id)


def unregister_bigrams(connection, text_id):
    """Remove bigram data for the specified Text

    Parameters
    ----------
    connection : tesserae.db.TessMongoConnection
        A connection to the Tesserae database
    text_id : ObjectId
        ObjectId of Text

    """
    text_id_str = str(text_id)
    for filename in glob.glob(os.path.join(
            BigramWriter.BIGRAM_DB_DIR, f'{text_id_str}_*.db')):
        os.remove(filename)


def lookup_bigrams(text_id, unit_type, feature, bigrams):
    """Looks up bigrams

    Parameters
    ----------
    text_id : ObjectId
        ObjectId associated with the Text of the bigrams to retrieve
    unit_type : {'line', 'phrase'}
        the type of Unit in which to look for bigrams
    feature : str
        the type of feature to which the bigram belongs
    bigrams : iterable of 2-tuple of int
        the bigrams of interest

    Returns
    -------
    dict[tuple[int, int], list[tuple(ObjectId, float)]]
        mapping between bigram and a list of tuples, where each tuple contains
        an ObjectId of a Unit to which the bigram belongs and a score for the
        Unit as calculated by the Tesserae formula

    """
    results = {}
    bigram_db_path = _create_bigram_db_path(
        text_id, unit_type, feature)
    print('#', bigram_db_path)
    conn = sqlite3.connect(bigram_db_path)
    with conn:
        for word1, word2 in bigrams:
            int1 = int(word1)
            int2 = int(word2)
            if int1 > int2:
                int1, int2 = int2, int1
            bigram = (int1, int2)
            results[bigram] = [
                (ObjectId(bytes(row[0])), row[1])
                for row in conn.execute(
                    'select unitid, score from bigrams where '
                    'word1=? and word2=?',
                    bigram
                )
            ]
    return results


def multitext_search(connection, matches, feature_type, unit_type, texts):
    """Retrieves Units containing matched bigrams

    Multitext search addresses the question, "Given these matches I've found
    through a Tesserae search, how frequently do these matching words occur
    together in other texts?"

    Multitext search takes the results from a previously completed Search as
    the starting point.  Looking at the Matches found in that Search, it looks
    in the unit of specified Texts for matching bigrams within each Match of
    the Search.

    Parameters
    ----------
    connection : TessMongoConnection
    matches : list of Match
        Match entities from which matched bigrams are taken
    feature_type : {'lemmata', 'form'}
        Feature type of words to search for
    unit_type : {'line', 'phrase'}
        Type of Units to look for
    texts : list of Text
        The Texts whose Units are to be searched

    Returns
    -------
    list of dict[(str, str), list of tuple(ObjectId, float)]
        each dictionary within the list corresponds in index to a match from
        ``matches``; the dictionary contains key-value pairs, where the key is
        a bigram and the value is a list of ObjectIds of Units of type
        ``unit_type`` that contains the bigram specified by the key; Units are
        restricted to those which are found in ``texts``
    """
    language = texts[0].language
    token2index = {
        f.token: f.index
        for f in connection.find(
            Feature.collection, feature=feature_type, language=language)}

    bigram_indices = set()
    for m in matches:
        for w1, w2 in itertools.combinations(sorted(m.matched_features), 2):
            bigram_indices.add((token2index[w1], token2index[w2]))

    bigram2units = defaultdict(list)
    for text in texts:
        bigram_data = lookup_bigrams(
            text.id, unit_type, feature_type, bigram_indices)
        for bigram, data in bigram_data.items():
            bigram2units[bigram].extend([
                u for u in data
            ])

    return [
        {
            bigram: bigram2units[
                (token2index[bigram[0]], token2index[bigram[1]])]
            for bigram in itertools.combinations(sorted(m.matched_features), 2)
        }
        for m in matches
    ]
