require "compiler/crystal/syntax"

class CommentParser < Crystal::Parser
  getter comments = {} of Int32 => String

  def skip_comment
    start = current_pos
    line = line_number
    super
    @comments[line] = "##{string_range(start)}".strip
  end

  def next_macro_token(macro_state, skip_whitespace)
    skip_macro_whitespace if skip_whitespace
    if !macro_state.delimiter_state && current_char == '#'
      @comments[line_number] = @reader.string.byte_slice(current_pos..).split('\n', 2).first.strip
    end
    super(macro_state, false)
  end
end

parser = CommentParser.new(STDIN.gets_to_end)
begin
  parser.parse
rescue Crystal::SyntaxException
end

parser.comments.each do |line, text|
  next if text.empty? || text.starts_with?("#!")
  next if text.matches?(/^#\s*(ameba:|crystal:\s*formatter\s+(off|on)\b)/)
  puts "#{line}\t#{text}"
end
