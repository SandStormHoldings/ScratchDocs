function(doc) {
    if (doc.journal)
    {
	for (var i=0;i<doc.journal.length;i++)
	{
	    var je = doc.journal[i];
	    if (je.attrs && je.attrs.unq_key) emit(je.attrs.unq_key,doc._id);
	}
    }
}

