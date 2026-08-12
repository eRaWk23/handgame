Drop flyers here.

This is the path for Facebook and Instagram, which cannot be scraped
reliably or within their terms. Save a flyer image out of a post, put it
in this folder, and the next run treats it like any other source: it gets
OCR'd, dated, checked against everything already on the site, and it lands
in the review queue.

What you can put here
---------------------
  * image files       .jpg .jpeg .png .webp .gif
  * links.txt         one URL per line. Image URLs are downloaded.
                      Other URLs are fetched and read. Anything after a
                      space on the line is kept as a note.

Optional head start
-------------------
Put a .txt next to an image with the same name (flyer.jpg -> flyer.txt)
and it will be used instead of guessing:

    title: 38th Annual Labor Day Stickgame Tournament
    location: Nespelem, WA
    tribe: Colville
    date: September 5 2026
    url: https://www.facebook.com/events/1234567890

Files stay here until you move them. Delete or move them to processed/
once they show up in a review queue.
