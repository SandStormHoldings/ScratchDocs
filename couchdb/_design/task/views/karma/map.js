function (doc) {
    if (doc.karma)
    {
	for (var dt in doc.karma) {
	    for (var giver in doc.karma[dt])
	    {
		var pts = 0;
		for (var receiver in doc.karma[dt][giver])
		{
		    pts += doc.karma[dt][giver][receiver];
		}
		emit([dt,giver],[doc._id,pts]);
	    }
	}
    }
}
