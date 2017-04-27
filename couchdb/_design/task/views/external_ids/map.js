function(doc) {
    if (doc.external_id != undefined)
    {
	emit(doc.external_id,doc._id);
    }
}
