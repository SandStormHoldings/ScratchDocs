function(doc) {
    if (doc.journal && doc.journal.length)
    {
	for (var i=0;i<doc.journal.length;i++)
	{
	    var j = doc.journal[i];
	    j.tid = doc._id;
  	    emit(j.created_at.split('T')[0],j)
	}
    }
}
