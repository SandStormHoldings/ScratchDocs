function (doc) {
    if (doc.karma)
    {
	for (var dt in doc.karma) {
	    for (var giver in doc.karma[dt])
	    {
		for (var receiver in doc.karma[dt][giver])
		{
		    var pts = doc.karma[dt][giver][receiver];
		    if (pts) emit([dt,receiver],[doc._id,pts]);
		}

	    }
	}
    }
}
