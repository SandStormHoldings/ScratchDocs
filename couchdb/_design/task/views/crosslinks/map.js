function(doc) {
    if (doc.cross_links != undefined)
    {
	for (var i=0;i<doc.cross_links.length;i++)
	{
	    emit(doc._id,doc.cross_links[i]);
	    emit(doc.cross_links[i],doc._id);
	}
    }
}
