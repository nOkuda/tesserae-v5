"""For retrieving search results"""


class TagHelper:
    """Helps build/retrieve tag information for a unit

    Attributes
    ----------
    connection : tesserae.db.mongodb.TessMongoConnection
    text_cache : dict [ObjectId, str]
        Given a text's database ID, tell what the display tag prefix should be
    """

    def __init__(self, connection, texts=None):
        """Initialize the TagHelper

        Parameters
        ----------
        connection : tesserae.db.mongodb.TessMongoConnection
        texts : list of tesserae.db.entities.Text, optional
            if specified, this TagHelper is prepopulated with tag information
            from the given Texts
        """
        self.connection = connection
        self.text_cache = {}
        if texts:
            for text in texts:
                tmp = []
                if text.author:
                    tmp.append(text.author)
                if text.title:
                    tmp.append(text.title)
                self.text_cache[text.id.binary] = ' '.join(tmp)

    def get_display_tag(self, text_id, unit_tags):
        """Create a display tag

        Parameters
        ----------
        unit_text_id : bson.objectid.ObjectId
            database ID to a text
        unit_tags : list of str
            the tags of the unit
        """
        tag_parts = []
        tag_parts.append(self.text_cache[text_id.binary])
        if unit_tags:
            tag_parts.append(unit_tags[0])
        return ' '.join(tag_parts)
