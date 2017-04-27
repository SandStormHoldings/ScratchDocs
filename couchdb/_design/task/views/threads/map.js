function(doc) {
    if (doc.external_thread_id != undefined)
    {
	emit(doc.external_thread_id,doc._id);
    }
}
